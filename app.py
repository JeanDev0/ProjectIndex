from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import random
import itertools

app = Flask(__name__)
app.config['SECRET_KEY'] = 'poker_secreto_123'
socketio = SocketIO(app, cors_allowed_origins="*")

NAIPES = ['♠', '♥', '♦', '♣']
VALORES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']

game_state = {
    'players': {}, 
    'turn_order': [],
    'current_turn_index': 0,
    'community_cards': [],
    'deck': [],
    'pot': 0,
    'current_min_bet': 50,
    'last_raise': 50, # Guarda o último aumento para validação
    'phase': 'waiting',
    'acted_this_round': [],
    'dealer_index': 0
}

def create_deck():
    return [{'valor': v, 'naipe': n} for n in NAIPES for v in VALORES]

def reset_game():
    game_state['players'].clear()
    game_state['turn_order'].clear()
    game_state['community_cards'] = []
    game_state['pot'] = 0
    game_state['phase'] = 'waiting'
    game_state['acted_this_round'].clear()
    game_state['dealer_index'] = 0

def evaluate_5_cards(cards):
    val_map = {'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13,'A':14}
    valores = sorted([val_map[c['valor']] for c in cards], reverse=True)
    naipes = [c['naipe'] for c in cards]
    
    is_flush = len(set(naipes)) == 1
    unique_vals = sorted(list(set(valores)), reverse=True)
    
    is_straight = False
    straight_high = 0
    if len(unique_vals) == 5:
        if unique_vals[0] - unique_vals[4] == 4:
            is_straight = True
            straight_high = unique_vals[0]
        elif unique_vals == [14, 5, 4, 3, 2]:
            is_straight = True
            straight_high = 5
            valores = [5, 4, 3, 2, 1]

    counts = {v: valores.count(v) for v in valores}
    count_freq = sorted(counts.values(), reverse=True)
    sorted_by_freq = sorted(counts.keys(), key=lambda x: (counts[x], x), reverse=True)

    if is_straight and is_flush:
        if straight_high == 14: return (9, sorted_by_freq) 
        return (8, [straight_high]) 
    if count_freq == [4, 1]: return (7, sorted_by_freq) 
    if count_freq == [3, 2]: return (6, sorted_by_freq) 
    if is_flush: return (5, valores) 
    if is_straight: return (4, [straight_high]) 
    if count_freq == [3, 1, 1]: return (3, sorted_by_freq) 
    if count_freq == [2, 2, 1]: return (2, sorted_by_freq) 
    if count_freq == [2, 1, 1, 1]: return (1, sorted_by_freq) 
    return (0, valores) 

def rotate_dealer():
    if len(game_state['turn_order']) > 0:
        game_state['dealer_index'] = (game_state['dealer_index'] + 1) % len(game_state['turn_order'])

def determine_winner():
    active_players = [sid for sid, p in game_state['players'].items() if p['status'] in ['active', 'all-in']]
    
    best_score = (-1, [])
    winners = []
    
    for sid in active_players:
        p = game_state['players'][sid]
        seven_cards = p['cards'] + game_state['community_cards']
        
        player_best = (-1, [])
        for combo in itertools.combinations(seven_cards, 5):
            score = evaluate_5_cards(list(combo))
            if score[0] > player_best[0] or (score[0] == player_best[0] and score[1] > player_best[1]):
                player_best = score
        
        if player_best[0] > best_score[0] or (player_best[0] == best_score[0] and player_best[1] > best_score[1]):
            best_score = player_best
            winners = [sid]
        elif player_best[0] == best_score[0] and player_best[1] == best_score[1]:
            winners.append(sid)

    share = game_state['pot'] // len(winners)
    nomes_ganhadores = [game_state['players'][sid]['name'] for sid in winners]
    
    for sid in winners:
        game_state['players'][sid]['chips'] += share

    rank_nomes = ["Carta Alta", "Um Par", "Dois Pares", "Trinca", "Sequência", "Flush", "Full House", "Quadra", "Straight Flush", "Royal Flush"]
    nome_da_mao = rank_nomes[best_score[0]]

    msg = f"Fim da Rodada! Vencedor(es): {', '.join(nomes_ganhadores)} com {nome_da_mao}! Ganhou {game_state['pot']} moedas."
    
    game_state['pot'] = 0
    game_state['phase'] = 'waiting'
    for sid in game_state['players']:
        game_state['players'][sid]['status'] = 'waiting'
        game_state['players'][sid]['cards'] = []
        game_state['players'][sid]['bet'] = 0

    rotate_dealer() 
    emit('game_update', game_state, broadcast=True)
    emit('show_winner', {'msg': msg}, broadcast=True)

def end_game_by_fold(winner_sid):
    p = game_state['players'][winner_sid]
    p['chips'] += game_state['pot']
    msg = f"{p['name']} venceu a rodada porque todos os outros desistiram! Levou {game_state['pot']} moedas."
    
    game_state['pot'] = 0
    game_state['phase'] = 'waiting'
    for sid in game_state['players']:
        game_state['players'][sid]['status'] = 'waiting'
        game_state['players'][sid]['cards'] = []
        game_state['players'][sid]['bet'] = 0
        
    rotate_dealer() 
    emit('game_update', game_state, broadcast=True)
    emit('show_winner', {'msg': msg}, broadcast=True)

def advance_phase():
    # Recolher apostas para o pote
    for sid in game_state['players']:
        if game_state['players'][sid]['status'] in ['active', 'all-in']:
            game_state['players'][sid]['bet'] = 0
            
    game_state['current_min_bet'] = 0
    game_state['last_raise'] = 50 # Reset no raise min para a proxima fase
    game_state['acted_this_round'].clear()
    
    if game_state['phase'] == 'pre-flop':
        game_state['phase'] = 'flop'
        game_state['community_cards'] = [game_state['deck'].pop() for _ in range(3)]
    elif game_state['phase'] == 'flop':
        game_state['phase'] = 'turn'
        game_state['community_cards'].append(game_state['deck'].pop())
    elif game_state['phase'] == 'turn':
        game_state['phase'] = 'river'
        game_state['community_cards'].append(game_state['deck'].pop())
    elif game_state['phase'] == 'river':
        determine_winner()
        return

    # Pula para o proximo jogador ativo baseado no dealer
    d_idx = game_state.get('dealer_index', 0)
    order_len = len(game_state['turn_order'])
    game_state['current_turn_index'] = -1
    
    for i in range(1, order_len + 1):
        idx = (d_idx + i) % order_len
        sid = game_state['turn_order'][idx]
        if game_state['players'][sid]['status'] == 'active':
            game_state['current_turn_index'] = idx
            break
            
    # Se todos os restantes estiverem All-in, avança a fase automaticamente
    if game_state['current_turn_index'] == -1:
        advance_phase()

# Rota para renderizar a interface gráfica
@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join_game')
def handle_join(data):
    sid = request.sid
    name = data.get('name', 'Jogador').strip()
    if not name: name = "Jogador Anônimo"
    
    if len(game_state['players']) >= 8:
        emit('error_msg', {'msg': 'Mesa cheia! Máximo de 8 jogadores.'})
        return

    game_state['players'][sid] = {
        'name': name,
        'chips': 5000,
        'cards': [],
        'bet': 0,
        'status': 'waiting'
    }
    game_state['turn_order'] = list(game_state['players'].keys())
    emit('game_update', game_state, broadcast=True)

@socketio.on('start_game')
def start_game():
    if len(game_state['players']) < 2:
        return 
    
    game_state['deck'] = create_deck()
    random.shuffle(game_state['deck'])
    game_state['pot'] = 0
    game_state['community_cards'] = []
    game_state['acted_this_round'].clear()
    
    order = list(game_state['players'].keys())
    game_state['turn_order'] = order
    game_state['phase'] = 'pre-flop'
    
    if game_state['dealer_index'] >= len(order):
        game_state['dealer_index'] = 0
        
    d_idx = game_state['dealer_index']
    
    sb_idx = (d_idx + 1) % len(order)
    bb_idx = (d_idx + 2) % len(order)
    utg_idx = (d_idx + 3) % len(order) 
    
    if len(order) == 2: 
        sb_idx = d_idx
        bb_idx = (d_idx + 1) % len(order)
        utg_idx = d_idx 

    game_state['current_turn_index'] = utg_idx
    
    for sid in order:
        game_state['players'][sid]['cards'] = [game_state['deck'].pop(), game_state['deck'].pop()]
        game_state['players'][sid]['status'] = 'active'
        game_state['players'][sid]['bet'] = 0

    # Desconto Automático: Small Blind
    sb_sid = order[sb_idx]
    game_state['players'][sb_sid]['chips'] -= 25
    game_state['players'][sb_sid]['bet'] = 25
    game_state['pot'] += 25
    
    # Desconto Automático: Big Blind
    bb_sid = order[bb_idx]
    game_state['players'][bb_sid]['chips'] -= 50
    game_state['players'][bb_sid]['bet'] = 50
    game_state['pot'] += 50
    
    game_state['current_min_bet'] = 50
    game_state['last_raise'] = 50

    emit('game_update', game_state, broadcast=True)

@socketio.on('player_action')
def handle_action(data):
    sid = request.sid
    action = data.get('action')
    amount = int(data.get('amount', 0))
    
    if sid != game_state['turn_order'][game_state['current_turn_index']]:
        return 
        
    player = game_state['players'][sid]
    
    if action == 'fold':
        player['status'] = 'folded'
        
    elif action == 'call':
        needed = game_state['current_min_bet'] - player['bet']
        if needed > 0:
            if player['chips'] <= needed: # All-in forçado se não tiver fichas (Cenário 18)
                action = 'all-in' 
            else:
                player['chips'] -= needed
                player['bet'] += needed
                game_state['pot'] += needed

    if action == 'raise':
        diff = amount - player['bet']
        if diff >= player['chips']: 
            action = 'all-in' # Aposta mais do que tem -> All-in
        elif amount < (game_state['current_min_bet'] + 5):
            return # Regra da casa: Aumento mínimo de 5 moedas acima da aposta atual
        else:
            player['chips'] -= diff
            player['bet'] = amount
            game_state['pot'] += diff
            game_state['last_raise'] = amount - game_state['current_min_bet']
            game_state['current_min_bet'] = amount
            game_state['acted_this_round'] = [sid]

    if action == 'all-in':
        all_in_fichas = player['chips']
        player['bet'] += all_in_fichas
        game_state['pot'] += all_in_fichas
        player['chips'] = 0
        player['status'] = 'all-in'
        
        if player['bet'] > game_state['current_min_bet']:
            game_state['last_raise'] = player['bet'] - game_state['current_min_bet']
            game_state['current_min_bet'] = player['bet']
            game_state['acted_this_round'] = [sid]

    if sid not in game_state['acted_this_round']:
        game_state['acted_this_round'].append(sid)

    # Regras de fim de rodada / Vitoria por Fold
    not_folded = [s for s, p in game_state['players'].items() if p['status'] != 'folded']
    if len(not_folded) == 1:
        end_game_by_fold(not_folded[0])
        return

    # Verifica se todos os ativos já agiram E igualaram a aposta
    round_ended = True
    for s in game_state['turn_order']:
        p = game_state['players'][s]
        if p['status'] == 'active':
            if s not in game_state['acted_this_round'] or p['bet'] != game_state['current_min_bet']:
                round_ended = False
                break

    if round_ended:
        advance_phase()
    else:
        # Passa o turno para o próximo ATIVO
        found_next = False
        next_idx = game_state['current_turn_index']
        for _ in range(len(game_state['turn_order'])):
            next_idx = (next_idx + 1) % len(game_state['turn_order'])
            next_sid = game_state['turn_order'][next_idx]
            if game_state['players'][next_sid]['status'] == 'active':
                game_state['current_turn_index'] = next_idx
                found_next = True
                break
        
        # Se não achou próximo ativo (ex: todos all in exceto 1), avança a fase
        if not found_next:
            advance_phase()

    emit('game_update', game_state, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    sid = request.sid
    if sid in game_state['players']:
        # 1. Garante que o dinheiro apostado por quem saiu vá para o pote
        game_state['pot'] += game_state['players'][sid]['bet']
        
        # 2. Remove o jogador da memória
        del game_state['players'][sid]
        
        # 3. Ajusta a ordem de turnos para não pular a vez de ninguém
        if sid in game_state['turn_order']:
            idx = game_state['turn_order'].index(sid)
            game_state['turn_order'].remove(sid)
            
            if len(game_state['turn_order']) > 0:
                if idx < game_state['current_turn_index']:
                    game_state['current_turn_index'] -= 1
                game_state['current_turn_index'] %= len(game_state['turn_order'])
                game_state['dealer_index'] %= len(game_state['turn_order'])
                
        if sid in game_state['acted_this_round']:
            game_state['acted_this_round'].remove(sid)

        # 4. AQUI ESTÁ A CORREÇÃO: Se sobrar menos de 2 pessoas, encerra tudo!
        if len(game_state['players']) < 2:
            reset_game()
            # Esse emit faz o navegador do jogador que sobrou dar um F5 automático e voltar pro lobby
            emit('game_reset', {'msg': 'A mesa ficou sem jogadores suficientes. A partida foi encerrada!'}, broadcast=True)
            return

        # 5. Se o jogo estava rodando, recalcula a rodada
        if game_state['phase'] != 'waiting':
            not_folded = [s for s, p in game_state['players'].items() if p['status'] != 'folded']
            
            # Se todo mundo desistiu ou saiu e sobrou só um, ele ganha o pote
            if len(not_folded) == 1:
                end_game_by_fold(not_folded[0])
                return
            
            # Verifica se a rodada deve virar agora que o jogador saiu
            round_ended = True
            for s in game_state['turn_order']:
                p = game_state['players'][s]
                if p['status'] == 'active':
                    if s not in game_state['acted_this_round'] or p['bet'] != game_state['current_min_bet']:
                        round_ended = False
                        break

            if round_ended:
                advance_phase()
            else:
                # Garante que a vez não caiu no colo de alguém que já deu All-in ou Fold
                if len(game_state['turn_order']) > 0:
                    curr_sid = game_state['turn_order'][game_state['current_turn_index']]
                    if game_state['players'][curr_sid]['status'] != 'active':
                        found_next = False
                        next_idx = game_state['current_turn_index']
                        for _ in range(len(game_state['turn_order'])):
                            next_idx = (next_idx + 1) % len(game_state['turn_order'])
                            next_sid = game_state['turn_order'][next_idx]
                            if game_state['players'][next_sid]['status'] == 'active':
                                game_state['current_turn_index'] = next_idx
                                found_next = True
                                break
                        if not found_next:
                            advance_phase()

        # Atualiza a tela de todos sem dar reload
        emit('game_update', game_state, broadcast=True)
        
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)