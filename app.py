from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random, itertools

app = Flask(__name__)
app.config['SECRET_KEY'] = 'indextech_secreto'
socketio = SocketIO(app, cors_allowed_origins="*")

# --- ESTADOS GLOBAIS ---
game_state = {'players': {}, 'turn_order': [], 'current_turn_index': 0, 'community_cards': [], 'deck': [], 'pot': 0, 'current_min_bet': 50, 'last_raise': 50, 'phase': 'waiting', 'acted_this_round': [], 'dealer_index': 0}
pifpaf_state = {'players': {}, 'turn_order': [], 'current_turn_index': 0, 'monte': [], 'lixo': [], 'phase': 'waiting', 'dealer_index': 0}
domino_state = {'players': {}, 'turn_order': [], 'current_turn_index': 0, 'boneyard': [], 'board': [], 'ends': {'left': None, 'right': None}, 'phase': 'waiting', 'consecutive_passes': 0, 'required_first_tile': None}

@app.route('/')
def index(): return render_template('index.html')

@socketio.on('join_game')
def handle_join(data):
    sid = request.sid; name = data.get('name', 'Jogador').strip(); gm = data.get('game', 'poker')
    if not name: name = "Anônimo"
    if gm == 'poker':
        if len(game_state['players']) >= 8: return emit('error_msg', {'msg': 'Poker cheio!'})
        game_state['players'][sid] = {'name': name, 'chips': 5000, 'cards': [], 'bet': 0, 'status': 'waiting'}
        if game_state['phase'] == 'waiting': game_state['turn_order'] = list(game_state['players'].keys())
        emit('game_update', game_state, broadcast=True)
    elif gm == 'pifpaf':
        if len(pifpaf_state['players']) >= 6: return emit('error_msg', {'msg': 'Pif-Paf cheio!'})
        pifpaf_state['players'][sid] = {'name': name, 'cards': [], 'status': 'waiting'}
        if pifpaf_state['phase'] == 'waiting': pifpaf_state['turn_order'] = list(pifpaf_state['players'].keys())
        emit('pifpaf_update', pifpaf_state, broadcast=True)
    elif gm == 'domino':
        if len(domino_state['players']) >= 4: return emit('error_msg', {'msg': 'Dominó cheio (Máx 4)!'})
        domino_state['players'][sid] = {'name': name, 'cards': []}
        if domino_state['phase'] == 'waiting': domino_state['turn_order'] = list(domino_state['players'].keys())
        emit('domino_update', domino_state, broadcast=True)

# ==========================================
# 🎲 MOTOR DO DOMINÓ
# ==========================================
def advance_domino_turn():
    domino_state['current_turn_index'] = (domino_state['current_turn_index'] + 1) % len(domino_state['turn_order'])

@socketio.on('start_domino')
def start_domino():
    pids = list(domino_state['players'].keys())
    if len(pids) < 2: return emit('error_msg', {'msg': 'Mínimo de 2 jogadores para o Dominó!'})
    
    # Loop de distribuição para julgar regras de 4 e 5 carroções
    while True:
        domino_state['boneyard'] = [{'left': i, 'right': j, 'id': f"d_{i}_{j}"} for i in range(7) for j in range(i, 7)]
        random.shuffle(domino_state['boneyard']); domino_state['board'] = []
        domino_state['ends'] = {'left': None, 'right': None}; domino_state['phase'] = 'playing'
        domino_state['consecutive_passes'] = 0; domino_state['turn_order'] = pids
        
        for sid in pids: domino_state['players'][sid]['cards'] = [domino_state['boneyard'].pop() for _ in range(7)]
        
        needs_redeal = False
        for sid in pids:
            p_name = domino_state['players'][sid]['name']
            doubles = [t for t in domino_state['players'][sid]['cards'] if t['left'] == t['right']]
            
            if len(doubles) >= 5:
                # 5 CARROÇÕES = VITÓRIA AUTOMÁTICA
                domino_state['phase'] = 'waiting'
                emit('domino_update', domino_state, broadcast=True)
                emit('action_notification', {'msg': f"🤯 {p_name} TIROU 5 CARROÇÕES E VENCEU AUTOMATICAMENTE!"}, broadcast=True)
                emit('pifpaf_showdown', {'winner': p_name, 'cards': domino_state['players'][sid]['cards'], 'msg': f"🏆 {p_name} Venceu (5 Carroções)!"}, broadcast=True)
                return
            elif len(doubles) == 4:
                # 4 CARROÇÕES = REEMBARALHA
                emit('action_notification', {'msg': f"🔄 {p_name} tirou 4 Carroções! O jogo será reembaralhado..."}, broadcast=True)
                socketio.sleep(3) # Pausa dramática para leitura
                needs_redeal = True
                break
                
        if not needs_redeal:
            break # A mão de todo mundo está válida, segue o jogo!
    
    # LÓGICA DE QUEM COMEÇA O JOGO
    max_double = -1; starter_sid = pids[0]; req_id = None
    for sid in pids:
        for t in domino_state['players'][sid]['cards']:
            if t['left'] == t['right'] and t['left'] > max_double: 
                max_double = t['left']; starter_sid = sid; req_id = t['id']
                
    if max_double == -1:
        max_sum = -1
        for sid in pids:
            for t in domino_state['players'][sid]['cards']:
                s = t['left'] + t['right']
                if s > max_sum: 
                    max_sum = s; starter_sid = sid; req_id = t['id']
                    
    domino_state['current_turn_index'] = domino_state['turn_order'].index(starter_sid)
    domino_state['required_first_tile'] = req_id
    starter_name = domino_state['players'][starter_sid]['name']
    
    emit('domino_update', domino_state, broadcast=True)
    if max_double != -1:
        nome_bucha = "Sena" if max_double == 6 else f"Bucha de {max_double}"
        aviso = f"🎲 A {nome_bucha} saiu! {starter_name} é obrigado a sair com ela."
    else:
        aviso = f"🎲 Sem bucha na mesa! {starter_name} sai com a maior peça."
        
    emit('action_notification', {'msg': aviso}, broadcast=True)

@socketio.on('domino_action')
def domino_action(data):
    sid = request.sid; action = data.get('action')
    if sid != domino_state['turn_order'][domino_state['current_turn_index']]: return
    player = domino_state['players'][sid]

    def has_playable(hand):
        if not domino_state['board']: return True
        l, r = domino_state['ends']['left'], domino_state['ends']['right']
        return any(t['left'] in (l, r) or t['right'] in (l, r) for t in hand)

    if action == 'play':
        tid = data.get('tile_id'); side = data.get('side')
        tile = next((t for t in player['cards'] if t['id'] == tid), None)
        if not tile: return
        
        # --- TRAVA DE SAÍDA ---
        if not domino_state['board']:
            if tid != domino_state.get('required_first_tile'):
                return emit('error_msg', {'msg': '❌ Você deve obrigatoriamente sair com a sua maior Bucha/Peça!'}, room=sid)
            
            domino_state['board'].append(tile); domino_state['ends']['left'] = tile['left']; domino_state['ends']['right'] = tile['right']
        else:
            target = domino_state['ends'][side]
            if side == 'left':
                if tile['right'] == target: pass 
                elif tile['left'] == target: tile = {'left': tile['right'], 'right': tile['left'], 'id': tile['id']} 
                else: return emit('error_msg', {'msg': '❌ A peça não encaixa na esquerda!'}, room=sid)
                domino_state['board'].insert(0, tile)
                domino_state['ends']['left'] = tile['left']
            else: 
                if tile['left'] == target: pass 
                elif tile['right'] == target: tile = {'left': tile['right'], 'right': tile['left'], 'id': tile['id']} 
                else: return emit('error_msg', {'msg': '❌ A peça não encaixa na direita!'}, room=sid)
                domino_state['board'].append(tile)
                domino_state['ends']['right'] = tile['right']
        
        player['cards'] = [t for t in player['cards'] if t['id'] != tid]
        domino_state['consecutive_passes'] = 0
        
        if len(player['cards']) == 0:
            domino_state['phase'] = 'waiting'; emit('domino_update', domino_state, broadcast=True)
            # NOTIFICAÇÃO DE VITÓRIA
            emit('action_notification', {'msg': f"🏆 {player['name']} BATEU O JOGO DE DOMINÓ!"}, broadcast=True)
            return emit('pifpaf_showdown', {'winner': player['name'], 'cards': [], 'msg': f"🏆 {player['name']} Bateu o Dominó!"}, broadcast=True)
            
        advance_domino_turn()

    elif action == 'draw':
        if has_playable(player['cards']): return emit('error_msg', {'msg': '❌ Jogue a peça que você tem!'}, room=sid)
        if not domino_state['boneyard']: return emit('error_msg', {'msg': 'O monte acabou. Passe a vez!'}, room=sid)
        drawn = domino_state['boneyard'].pop(); player['cards'].append(drawn)
        if not has_playable([drawn]):
            emit('action_notification', {'msg': f"💤 {player['name']} comprou e passou."}, broadcast=True)
            domino_state['consecutive_passes'] += 1; advance_domino_turn()
        else: emit('action_notification', {'msg': f"🍀 {player['name']} comprou e encontrou a peça!"}, broadcast=True)

    elif action == 'pass':
        if has_playable(player['cards']): return emit('error_msg', {'msg': '❌ Você tem peça na mão!'}, room=sid)
        if domino_state['boneyard']: return emit('error_msg', {'msg': '❌ Compre do monte primeiro!'}, room=sid)
        emit('action_notification', {'msg': f"🛑 {player['name']} passou a vez."}, broadcast=True); domino_state['consecutive_passes'] += 1
        if domino_state['consecutive_passes'] >= len(domino_state['players']):
            vencedor = min(domino_state['players'].values(), key=lambda p: sum(t['left']+t['right'] for t in p['cards']))
            domino_state['phase'] = 'waiting'; emit('domino_update', domino_state, broadcast=True)
            # NOTIFICAÇÃO JOGO TRANCADO
            emit('action_notification', {'msg': f"🔒 JOGO TRANCADO! {vencedor['name']} ganhou por menos pontos!"}, broadcast=True)
            return emit('pifpaf_showdown', {'winner': vencedor['name'], 'cards': [], 'msg': f"🔒 Jogo Trancado! {vencedor['name']} venceu!"}, broadcast=True)
        advance_domino_turn()
    emit('domino_update', domino_state, broadcast=True)

# ==========================================
# MOTOR DO PIF-PAF E POKER (MANTIDOS)
# ==========================================
NAIPES = ['♠', '♥', '♦', '♣']; VALORES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
def create_deck_cards(m=1):
    d=[]; idx=0
    for _ in range(m):
        for n in NAIPES:
            for v in VALORES: d.append({'valor': v, 'naipe': n, 'id': f"{v}{n}_{idx}"}); idx+=1
    return d

def is_valid_pifpaf(cards):
    if len(cards) != 9: return False
    vmap = {'A':1,'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13}
    def is_grp(c1,c2,c3):
        if c1['valor']==c2['valor']==c3['valor'] and len({c1['naipe'],c2['naipe'],c3['naipe']})==3: return True
        if c1['naipe']==c2['naipe']==c3['naipe']:
            v=sorted([vmap[c1['valor']],vmap[c2['valor']],vmap[c3['valor']]])
            if v==[v[0],v[0]+1,v[0]+2] or v==[1,12,13]: return True
        return False
    def bt(rem):
        if not rem: return True
        for i in range(1,len(rem)):
            for j in range(i+1,len(rem)):
                if is_grp(rem[0],rem[i],rem[j]):
                    nr=rem[:]; nr.pop(j); nr.pop(i); nr.pop(0)
                    if bt(nr): return True
        return False
    return bt(cards)

@socketio.on('start_pifpaf')
def start_pifpaf():
    pids = list(pifpaf_state['players'].keys())
    if len(pids)<2: return 
    pifpaf_state['monte'] = create_deck_cards(2); random.shuffle(pifpaf_state['monte']); pifpaf_state['lixo'] = []; pifpaf_state['turn_order'] = pids; pifpaf_state['phase'] = 'playing'
    pifpaf_state['dealer_index'] = (pifpaf_state['dealer_index']+1)%len(pids) if 'dealer_index' in pifpaf_state else 0
    pifpaf_state['current_turn_index'] = (pifpaf_state['dealer_index'] + 1) % len(pids)
    for sid in pids: pifpaf_state['players'][sid]['cards'] = [pifpaf_state['monte'].pop() for _ in range(9)]
    pifpaf_state['lixo'].append(pifpaf_state['monte'].pop()); emit('pifpaf_update', pifpaf_state, broadcast=True)

@socketio.on('pifpaf_action')
def pifpaf_action(data):
    sid = request.sid; act = data.get('action'); p = pifpaf_state['players'].get(sid)
    if not p: return
    if act == 'intercept_bater' and len(p['cards'])==9 and pifpaf_state['lixo']:
        for i, c in enumerate(p['cards']):
            if c.get('id') == data.get('card_id'):
                tst = p['cards'].copy(); desc = tst.pop(i); tst.append(pifpaf_state['lixo'][-1])
                if not is_valid_pifpaf(tst): return emit('error_msg', {'msg': '❌ ALARME FALSO!'}, room=sid)
                pifpaf_state['lixo'].pop(); p['cards'] = tst; pifpaf_state['lixo'].append(desc); pifpaf_state['phase'] = 'waiting'
                for s in pifpaf_state['players']: pifpaf_state['players'][s]['cards'] = []
                emit('pifpaf_update', pifpaf_state, broadcast=True)
                return emit('pifpaf_showdown', {'winner': p['name'], 'cards': p['cards'], 'msg': f"⚡ {p['name']} PASSOU NA FRENTE E BATEU!"}, broadcast=True)
    if sid != pifpaf_state['turn_order'][pifpaf_state['current_turn_index']]: return
    if act == 'draw_monte' and pifpaf_state['monte']:
        p['cards'].append(pifpaf_state['monte'].pop())
        if not pifpaf_state['monte'] and len(pifpaf_state['lixo'])>1: topo=pifpaf_state['lixo'].pop(); pifpaf_state['monte']=pifpaf_state['lixo']; random.shuffle(pifpaf_state['monte']); pifpaf_state['lixo']=[topo]
    elif act == 'draw_lixo' and pifpaf_state['lixo']: p['cards'].append(pifpaf_state['lixo'].pop())
    elif act == 'discard':
        for i, c in enumerate(p['cards']):
            if c.get('id') == data.get('card_id'): pifpaf_state['lixo'].append(p['cards'].pop(i)); pifpaf_state['current_turn_index'] = (pifpaf_state['current_turn_index']+1)%len(pifpaf_state['turn_order']); break
    elif act == 'bater':
        for i, c in enumerate(p['cards']):
            if c.get('id') == data.get('card_id'):
                tst = p['cards'].copy(); desc = tst.pop(i)
                if not is_valid_pifpaf(tst): return emit('error_msg', {'msg': '❌ Mão Inválida!'}, room=sid)
                p['cards'] = tst; pifpaf_state['lixo'].append(desc); pifpaf_state['phase'] = 'waiting'
                for s in pifpaf_state['players']: pifpaf_state['players'][s]['cards'] = []
                emit('pifpaf_update', pifpaf_state, broadcast=True)
                return emit('pifpaf_showdown', {'winner': p['name'], 'cards': p['cards'], 'msg': f"🏆 {p['name']} Bateu!"}, broadcast=True)
    emit('pifpaf_update', pifpaf_state, broadcast=True)

# POKER
def advance_phase():
    for sid in game_state['players']: game_state['players'][sid]['bet'] = 0
    game_state['current_min_bet']=0; game_state['last_raise']=50; game_state['acted_this_round'].clear()
    if game_state['phase'] == 'pre-flop': game_state['phase'] = 'flop'; game_state['community_cards'] = [game_state['deck'].pop() for _ in range(3)]
    elif game_state['phase'] in ['flop', 'turn']: game_state['phase'] = 'turn' if game_state['phase']=='flop' else 'river'; game_state['community_cards'].append(game_state['deck'].pop())
    elif game_state['phase'] == 'river':
        w = [s for s,p in game_state['players'].items() if p['status'] in ['active','all-in']][0]
        msg = f"🏆 Fim da mão!"; game_state['pot'] = 0; game_state['phase'] = 'waiting'
        for s in game_state['players']: game_state['players'][s]['status']='waiting'; game_state['players'][s]['cards']=[]; game_state['players'][s]['bet']=0
        emit('game_update', game_state, broadcast=True); return emit('action_notification', {'msg': msg}, broadcast=True)
    d_idx = game_state.get('dealer_index', 0); n = len(game_state['turn_order']); game_state['current_turn_index'] = -1
    for i in range(1, n+1):
        idx = (d_idx+i)%n
        if game_state['players'][game_state['turn_order'][idx]]['status'] == 'active': game_state['current_turn_index']=idx; break
    if game_state['current_turn_index']==-1: advance_phase()

@socketio.on('start_game')
def start_poker():
    vivos = [s for s,p in game_state['players'].items() if p['chips']>0]
    if len(vivos)<2: return
    game_state['deck'] = create_deck_cards(); random.shuffle(game_state['deck']); game_state['pot']=0; game_state['community_cards']=[]; game_state['acted_this_round'].clear()
    game_state['turn_order']=vivos; game_state['phase']='pre-flop'; game_state['current_turn_index'] = 0
    for s in vivos: game_state['players'][s]['cards'] = [game_state['deck'].pop(), game_state['deck'].pop()]; game_state['players'][s]['status']='active'
    emit('game_update', game_state, broadcast=True)

@socketio.on('player_action')
def poker_action(data):
    sid = request.sid; act = data.get('action'); amt = int(data.get('amount',0)); p = game_state['players'][sid]
    if sid != game_state['turn_order'][game_state['current_turn_index']]: return
    if act == 'fold': p['status'] = 'folded'
    elif act == 'call': n = game_state['current_min_bet']-p['bet']; p['chips']-=n; p['bet']+=n; game_state['pot']+=n
    elif act == 'raise': diff = amt-p['bet']; p['chips']-=diff; p['bet']=amt; game_state['pot']+=diff; game_state['current_min_bet']=amt; game_state['acted_this_round']=[sid]; emit('action_notification', {'msg': f"🔥 {p['name']} AUMENTOU!"}, broadcast=True)
    elif act == 'all-in': allin = p['chips']; p['bet']+=allin; game_state['pot']+=allin; p['chips']=0; p['status']='all-in'; game_state['acted_this_round']=[sid]; emit('action_notification', {'msg': f"💥 {p['name']} deu ALL-IN!"}, broadcast=True)
    if sid not in game_state['acted_this_round']: game_state['acted_this_round'].append(sid)
    if sum(1 for s in game_state['turn_order'] if game_state['players'][s]['status']!='folded') == 1: advance_phase()
    if all(game_state['players'][s]['status']!='active' or (s in game_state['acted_this_round'] and game_state['players'][s]['bet']==game_state['current_min_bet']) for s in game_state['turn_order']): advance_phase()
    else:
        for _ in range(len(game_state['turn_order'])):
            game_state['current_turn_index'] = (game_state['current_turn_index']+1)%len(game_state['turn_order'])
            if game_state['players'][game_state['turn_order'][game_state['current_turn_index']]]['status'] == 'active': break
    emit('game_update', game_state, broadcast=True)

if __name__ == '__main__': socketio.run(app, host='0.0.0.0', port=5000, debug=True)