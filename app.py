from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import itertools

app = Flask(__name__)
app.config['SECRET_KEY'] = 'indextech_secreto'
socketio = SocketIO(app, cors_allowed_origins="*")

NAIPES = ['♠', '♥', '♦', '♣']
VALORES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
VALORES_ORDER = {'2':2, '3':3, '4':4, '5':5, '6':6, '7':7, '8':8, '9':9, '10':10, 'J':11, 'Q':12, 'K':13, 'A':14}

# --- ESTADOS GLOBAIS ---
game_state = { # POKER
    'players': {}, 'turn_order': [], 'current_turn_index': 0, 'community_cards': [],
    'deck': [], 'pot': 0, 'current_min_bet': 50, 'last_raise': 50, 'phase': 'waiting',
    'acted_this_round': [], 'dealer_index': 0
}

pifpaf_state = { # PIF-PAF
    'players': {}, 'turn_order': [], 'current_turn_index': 0,
    'monte': [], 'lixo': [], 'phase': 'waiting', 'dealer_index': 0
}

# --- FUNÇÕES COMPARTILHADAS ---
def create_deck(multiplicator=1):
    return [{'valor': v, 'naipe': n} for n in NAIPES for v in VALORES] * multiplicator

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join_game')
def handle_join(data):
    sid = request.sid
    name = data.get('name', 'Jogador').strip()
    game_mode = data.get('game', 'poker') 
    if not name: name = "Jogador Anônimo"
    
    if game_mode == 'poker':
        if len(game_state['players']) >= 8:
            emit('error_msg', {'msg': 'Mesa cheia! Máximo de 8 jogadores.'})
            return
        game_state['players'][sid] = {'name': name, 'chips': 5000, 'cards': [], 'bet': 0, 'status': 'waiting', 'game': 'poker'}
        if game_state['phase'] == 'waiting':
            game_state['turn_order'] = list(game_state['players'].keys())
        emit('game_update', game_state, broadcast=True)
        
    elif game_mode == 'pifpaf':
        if len(pifpaf_state['players']) >= 6:
            emit('error_msg', {'msg': 'Mesa cheia! O Pif-Paf aceita no máximo 6 jogadores.'})
            return
        pifpaf_state['players'][sid] = {'name': name, 'cards': [], 'status': 'waiting', 'game': 'pifpaf'}
        if pifpaf_state['phase'] == 'waiting':
            pifpaf_state['turn_order'] = list(pifpaf_state['players'].keys())
        emit('pifpaf_update', pifpaf_state, broadcast=True)


# ==========================================
#             MOTOR DO PIF-PAF
# ==========================================
def reset_pifpaf():
    pifpaf_state['players'].clear()
    pifpaf_state['turn_order'].clear()
    pifpaf_state['monte'] = []
    pifpaf_state['lixo'] = []
    pifpaf_state['phase'] = 'waiting'
    pifpaf_state['dealer_index'] = 0

@socketio.on('start_pifpaf')
def start_pifpaf():
    jogadores = list(pifpaf_state['players'].keys())
    if len(jogadores) < 2:
        return 
    
    # 2 Baralhos, Sem Coringa
    pifpaf_state['monte'] = create_deck(2)
    random.shuffle(pifpaf_state['monte'])
    pifpaf_state['lixo'] = []
    
    pifpaf_state['turn_order'] = jogadores
    pifpaf_state['phase'] = 'playing'
    
    if pifpaf_state['dealer_index'] >= len(jogadores): pifpaf_state['dealer_index'] = 0
    pifpaf_state['current_turn_index'] = (pifpaf_state['dealer_index'] + 1) % len(jogadores)
    
    # Distribui 9 cartas para cada um
    for sid in jogadores:
        pifpaf_state['players'][sid]['cards'] = [pifpaf_state['monte'].pop() for _ in range(9)]
        pifpaf_state['players'][sid]['status'] = 'playing'

    # Vira a primeira carta no lixo
    pifpaf_state['lixo'].append(pifpaf_state['monte'].pop())
    
    emit('pifpaf_update', pifpaf_state, broadcast=True)

@socketio.on('pifpaf_action')
def pifpaf_action(data):
    sid = request.sid
    if sid != pifpaf_state['turn_order'][pifpaf_state['current_turn_index']]: return
    
    action = data.get('action')
    player = pifpaf_state['players'][sid]

    # COMPRAR DO MONTE
    if action == 'draw_monte':
        if len(player['cards']) == 9 and len(pifpaf_state['monte']) > 0:
            player['cards'].append(pifpaf_state['monte'].pop())
            # Se o monte esvaziar, embaralha o lixo e vira o novo monte
            if len(pifpaf_state['monte']) == 0 and len(pifpaf_state['lixo']) > 1:
                topo = pifpaf_state['lixo'].pop()
                pifpaf_state['monte'] = pifpaf_state['lixo']
                random.shuffle(pifpaf_state['monte'])
                pifpaf_state['lixo'] = [topo]

    # COMPRAR DO LIXO
    elif action == 'draw_lixo':
        if len(player['cards']) == 9 and len(pifpaf_state['lixo']) > 0:
            player['cards'].append(pifpaf_state['lixo'].pop())

    # DESCARTAR UMA CARTA E PASSAR A VEZ
    elif action == 'discard':
        if len(player['cards']) == 10:
            c_idx = data.get('card_index')
            if 0 <= c_idx < 10:
                carta_descartada = player['cards'].pop(c_idx)
                pifpaf_state['lixo'].append(carta_descartada)
                pifpaf_state['current_turn_index'] = (pifpaf_state['current_turn_index'] + 1) % len(pifpaf_state['turn_order'])

    # BATER (VENCER O JOGO)
    elif action == 'bater':
        if len(player['cards']) == 10:
            c_idx = data.get('card_index')
            if 0 <= c_idx < 10:
                carta_descartada = player['cards'].pop(c_idx)
                pifpaf_state['lixo'].append(carta_descartada)
                
                vencedor = player['name']
                cartas_vencedoras = player['cards'].copy()
                
                # Reseta para a próxima
                pifpaf_state['phase'] = 'waiting'
                pifpaf_state['dealer_index'] = (pifpaf_state['dealer_index'] + 1) % len(pifpaf_state['turn_order'])
                for s in pifpaf_state['players']: pifpaf_state['players'][s]['cards'] = []
                
                emit('pifpaf_update', pifpaf_state, broadcast=True)
                # Mostra o painel com as cartas APENAS do vencedor
                emit('pifpaf_winner', {'name': vencedor, 'cards': cartas_vencedoras, 'msg': f"🏆 {vencedor} Bateu o Jogo!"}, broadcast=True)
                return

    emit('pifpaf_update', pifpaf_state, broadcast=True)


# ==========================================
#             MOTOR DO POKER
# ==========================================
# (O código original do Poker continua perfeitamente intacto aqui embaixo)

def evaluate_5_cards_poker(cards):
    return evaluate_5_cards(cards)

def determine_winner():
    active_players = [sid for sid, p in game_state['players'].items() if p['status'] in ['active', 'all-in']]
    best_score = (-1, [])
    winners = []
    player_best_hands = {}
    
    for sid in active_players:
        p = game_state['players'][sid]
        seven_cards = p['cards'] + game_state['community_cards']
        player_best = (-1, [])
        for combo in itertools.combinations(seven_cards, 5):
            score = evaluate_5_cards(list(combo))
            if score[0] > player_best[0] or (score[0] == player_best[0] and score[1] > player_best[1]): player_best = score
        player_best_hands[sid] = player_best
        if player_best[0] > best_score[0] or (player_best[0] == best_score[0] and player_best[1] > best_score[1]):
            best_score = player_best; winners = [sid]
        elif player_best[0] == best_score[0] and player_best[1] == best_score[1]:
            winners.append(sid)

    rank_nomes = ["Carta Alta", "Um Par", "Dois Pares", "Trinca", "Sequência", "Flush", "Full House", "Quadra", "Straight Flush", "Royal Flush"]
    showdown_hands = []
    for sid in active_players:
        rank_idx = player_best_hands[sid][0]
        showdown_hands.append({
            'name': game_state['players'][sid]['name'], 'cards': game_state['players'][sid]['cards'],
            'hand_name': rank_nomes[rank_idx], 'is_winner': sid in winners      
        })

    share = game_state['pot'] // len(winners)
    nomes_ganhadores = [game_state['players'][sid]['name'] for sid in winners]
    for sid in winners: game_state['players'][sid]['chips'] += share

    nome_da_mao = rank_nomes[best_score[0]]
    msg = f"🏆 Vencedor(es): {', '.join(nomes_ganhadores)} com {nome_da_mao}!\nPuxou {game_state['pot']} MBs."
    
    game_state['pot'] = 0; game_state['phase'] = 'waiting'
    for sid in game_state['players']:
        game_state['players'][sid]['status'] = 'waiting'; game_state['players'][sid]['cards'] = []; game_state['players'][sid]['bet'] = 0

    rotate_dealer() 
    emit('game_update', game_state, broadcast=True)
    emit('showdown', {'hands': showdown_hands, 'msg': msg}, broadcast=True)

def end_game_by_fold(winner_sid):
    p = game_state['players'][winner_sid]
    game_state['last_winner_cards'] = p['cards'].copy()
    game_state['last_winner_name'] = p['name']
    p['chips'] += game_state['pot']
    msg = f"🛑 {p['name']} venceu por desistência da mesa e puxou {game_state['pot']} MBs!"
    
    game_state['pot'] = 0; game_state['phase'] = 'waiting'
    for sid in game_state['players']:
        game_state['players'][sid]['status'] = 'waiting'; game_state['players'][sid]['cards'] = []; game_state['players'][sid]['bet'] = 0
        
    rotate_dealer() 
    emit('game_update', game_state, broadcast=True)
    emit('showdown', {'hands': [], 'msg': msg}, broadcast=True)
    emit('ask_show_cards', {}, room=winner_sid)

def advance_phase():
    for sid in game_state['players']: game_state['players'][sid]['bet'] = 0
    game_state['current_min_bet'] = 0; game_state['last_raise'] = 50; game_state['acted_this_round'].clear()
    
    if game_state['phase'] == 'pre-flop':
        game_state['phase'] = 'flop'; game_state['community_cards'] = [game_state['deck'].pop() for _ in range(3)]
    elif game_state['phase'] == 'flop':
        game_state['phase'] = 'turn'; game_state['community_cards'].append(game_state['deck'].pop())
    elif game_state['phase'] == 'turn':
        game_state['phase'] = 'river'; game_state['community_cards'].append(game_state['deck'].pop())
    elif game_state['phase'] == 'river':
        determine_winner(); return

    d_idx = game_state.get('dealer_index', 0)
    order_len = len(game_state['turn_order'])
    game_state['current_turn_index'] = -1
    for i in range(1, order_len + 1):
        idx = (d_idx + i) % order_len
        sid = game_state['turn_order'][idx]
        if game_state['players'][sid]['status'] == 'active':
            game_state['current_turn_index'] = idx; break
    if game_state['current_turn_index'] == -1: advance_phase()


@socketio.on('start_game')
def start_game():
    jogadores_vivos = [sid for sid in list(game_state['players'].keys()) if game_state['players'][sid]['chips'] > 0]
    for sid in list(game_state['players'].keys()):
        if game_state['players'][sid]['chips'] <= 0: game_state['players'][sid]['status'] = 'busted'

    if len(jogadores_vivos) < 2: return emit('error_msg', {'msg': 'Não há jogadores suficientes com MBs para iniciar.'})
    
    game_state['deck'] = create_deck()
    random.shuffle(game_state['deck'])
    game_state['pot'] = 0; game_state['community_cards'] = []; game_state['acted_this_round'].clear()
    game_state['turn_order'] = jogadores_vivos; game_state['phase'] = 'pre-flop'
    
    if game_state['dealer_index'] >= len(jogadores_vivos): game_state['dealer_index'] = 0
    d_idx = game_state['dealer_index']
    sb_idx = (d_idx + 1) % len(jogadores_vivos)
    bb_idx = (d_idx + 2) % len(jogadores_vivos)
    utg_idx = (d_idx + 3) % len(jogadores_vivos) 
    
    if len(jogadores_vivos) == 2: sb_idx = d_idx; bb_idx = (d_idx + 1) % len(jogadores_vivos); utg_idx = d_idx 
    game_state['current_turn_index'] = utg_idx
    
    for sid in jogadores_vivos:
        game_state['players'][sid]['cards'] = [game_state['deck'].pop(), game_state['deck'].pop()]
        game_state['players'][sid]['status'] = 'active'; game_state['players'][sid]['bet'] = 0

    sb_sid = jogadores_vivos[sb_idx]
    sb_desc = min(25, game_state['players'][sb_sid]['chips'])
    game_state['players'][sb_sid]['chips'] -= sb_desc; game_state['players'][sb_sid]['bet'] = sb_desc; game_state['pot'] += sb_desc
    
    bb_sid = jogadores_vivos[bb_idx]
    bb_desc = min(50, game_state['players'][bb_sid]['chips'])
    game_state['players'][bb_sid]['chips'] -= bb_desc; game_state['players'][bb_sid]['bet'] = bb_desc; game_state['pot'] += bb_desc
    
    game_state['current_min_bet'] = 50; game_state['last_raise'] = 50
    emit('game_update', game_state, broadcast=True)

@socketio.on('player_action')
def handle_action(data):
    sid = request.sid; action = data.get('action'); amount = int(data.get('amount', 0))
    if sid != game_state['turn_order'][game_state['current_turn_index']]: return 
        
    player = game_state['players'][sid]
    if action == 'fold': player['status'] = 'folded'
    elif action == 'call':
        needed = game_state['current_min_bet'] - player['bet']
        if needed > 0:
            if player['chips'] <= needed: action = 'all-in' 
            else: player['chips'] -= needed; player['bet'] += needed; game_state['pot'] += needed

    if action == 'raise':
        diff = amount - player['bet']
        if diff >= player['chips']: action = 'all-in' 
        elif amount < (game_state['current_min_bet'] + 5): return 
        else:
            player['chips'] -= diff; player['bet'] = amount; game_state['pot'] += diff
            game_state['last_raise'] = amount - game_state['current_min_bet']; game_state['current_min_bet'] = amount; game_state['acted_this_round'] = [sid] 

    if action == 'all-in':
        all_in_fichas = player['chips']; player['bet'] += all_in_fichas; game_state['pot'] += all_in_fichas
        player['chips'] = 0; player['status'] = 'all-in'
        if player['bet'] > game_state['current_min_bet']:
            game_state['last_raise'] = player['bet'] - game_state['current_min_bet']; game_state['current_min_bet'] = player['bet']; game_state['acted_this_round'] = [sid]

    if sid not in game_state['acted_this_round']: game_state['acted_this_round'].append(sid)

    not_folded = [s for s, p in game_state['players'].items() if p['status'] != 'folded']
    if len(not_folded) == 1:
        end_game_by_fold(not_folded[0]); return

    round_ended = True
    for s in game_state['turn_order']:
        p = game_state['players'][s]
        if p['status'] == 'active':
            if s not in game_state['acted_this_round'] or p['bet'] != game_state['current_min_bet']:
                round_ended = False; break

    if round_ended: advance_phase()
    else:
        found_next = False
        next_idx = game_state['current_turn_index']
        if len(game_state['turn_order']) > 0:
            for _ in range(len(game_state['turn_order'])):
                next_idx = (next_idx + 1) % len(game_state['turn_order'])
                next_sid = game_state['turn_order'][next_idx]
                if game_state['players'][next_sid]['status'] == 'active':
                    game_state['current_turn_index'] = next_idx; found_next = True; break
            if not found_next: advance_phase()

    emit('game_update', game_state, broadcast=True)

@socketio.on('choose_show_cards')
def handle_show_cards(data):
    if data.get('show'):
        cards = game_state.get('last_winner_cards', []); name = game_state.get('last_winner_name', 'Jogador')
        if cards: emit('showdown', {'hands': [{'name': name, 'cards': cards, 'hand_name': 'Blefe Revelado', 'is_winner': True}], 'msg': f"🔥 {name} deu carteira!"}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    # Remove do Poker
    if sid in game_state['players']:
        game_state['pot'] += game_state['players'][sid]['bet']
        del game_state['players'][sid]
        if sid in game_state['turn_order']:
            idx = game_state['turn_order'].index(sid); game_state['turn_order'].remove(sid)
            if len(game_state['turn_order']) > 0:
                if idx < game_state['current_turn_index']: game_state['current_turn_index'] -= 1
                game_state['current_turn_index'] %= len(game_state['turn_order'])
        if sid in game_state['acted_this_round']: game_state['acted_this_round'].remove(sid)
        if len(game_state['players']) < 2: reset_game(); emit('game_reset', {'msg': 'Mesa vazia. Jogo encerrado!'}, broadcast=True); return
        if game_state['phase'] != 'waiting':
            not_folded = [s for s, p in game_state['players'].items() if p['status'] != 'folded']
            if len(not_folded) == 1: end_game_by_fold(not_folded[0]); return
            round_ended = True
            for s in game_state['turn_order']:
                if game_state['players'][s]['status'] == 'active' and (s not in game_state['acted_this_round'] or game_state['players'][s]['bet'] != game_state['current_min_bet']): round_ended = False; break
            if round_ended: advance_phase()
        emit('game_update', game_state, broadcast=True)
        
    # Remove do Pif-Paf
    if sid in pifpaf_state['players']:
        del pifpaf_state['players'][sid]
        if sid in pifpaf_state['turn_order']:
            idx = pifpaf_state['turn_order'].index(sid); pifpaf_state['turn_order'].remove(sid)
            if len(pifpaf_state['turn_order']) > 0:
                if idx < pifpaf_state['current_turn_index']: pifpaf_state['current_turn_index'] -= 1
                pifpaf_state['current_turn_index'] %= len(pifpaf_state['turn_order'])
        if len(pifpaf_state['players']) < 2: reset_pifpaf(); emit('game_reset', {'msg': 'Mesa de Pif-Paf vazia!'}, broadcast=True)
        emit('pifpaf_update', pifpaf_state, broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)