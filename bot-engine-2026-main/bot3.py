import eval7
import random
from pkbot.actions import ActionFold, ActionCall, ActionCheck, ActionRaise, ActionBid
from pkbot.states import GameInfo, PokerState
from pkbot.base import BaseBot
from pkbot.runner import parse_args, run_bot

# Paste your full 1326-line dictionary here!
PREFLOP_EQUITY = {
    'AhAs': 0.8662,
    'KhKs': 0.8195,
    # ...
}

class Player(BaseBot):
    def __init__(self):
        self.preflop_equity = PREFLOP_EQUITY
        self.total_hands = 0

    def on_hand_start(self, game_info: GameInfo, current_state: PokerState):
        self.total_hands += 1

    def on_hand_end(self, game_info: GameInfo, current_state: PokerState):
        pass

    # ====================================
    # FAST PROBABILITY CALCULATION
    # ====================================
    def get_p_win(self, current_state):
        """Replaces the slow Monte Carlo loop with instant lookups/evals"""
        # PREFLOP
        if not current_state.board:
            key = "".join(sorted(current_state.my_hand))
            return self.preflop_equity.get(key, 0.50)
            
        # POSTFLOP
        try:
            my_eval = [eval7.Card(c) for c in current_state.my_hand]
            board_eval = [eval7.Card(c) for c in current_state.board]
            val = eval7.evaluate(my_eval + board_eval)
            hand_type = eval7.handtype(val)
            
            equity_map = {
                'High Card': 0.15, 'Pair': 0.45, 'Two Pair': 0.65,
                'Three of a Kind': 0.75, 'Straight': 0.85, 'Flush': 0.90,
                'Full House': 0.95, 'Four of a Kind': 0.98, 'Straight Flush': 1.0
            }
            return equity_map.get(hand_type, 0.15)
        except:
            return 0.15

    # ====================================
    # USER'S ROUNDING FUNCTION
    # ====================================
    @staticmethod
    def _round_to_multiple(number, multiple):
        total = number // multiple
        if (number - total * multiple) / multiple > 0.5:
            total += 1
        return total * multiple

    # ====================================
    # ENGINE CORE (YOUR DECISION LOGIC)
    # ====================================
    def get_move(self, game_info: GameInfo, current_state: PokerState):
        street = current_state.street

        # 1. SNEAK PEEK AUCTION PHASE
        if street == 'auction':
            p_win = self.get_p_win(current_state)
            if p_win > 0.65:
                return ActionBid(min(20, current_state.my_chips, current_state.pot))
            return ActionBid(0)

        # 2. GET WIN PROBABILITY
        p_win = self.get_p_win(current_state)

        # Apply Sneak Peek info penalty to our probability
        if current_state.opp_revealed_cards and p_win <= 0.45:
            for c in current_state.opp_revealed_cards:
                if c[0] in ['A', 'K', 'Q', 'J']:
                    p_win -= 0.15 
                    break

        pot = current_state.pot
        cost = current_state.cost_to_call
        BB = 20 # Assuming standard Big Blind is 20
        
        # 3. YOUR EXACT MATHEMATICAL DECISION TREE
        if p_win > 0.5:
            if current_state.can_act(ActionRaise):
                # Your raise sizing heuristic
                factor = int(max(BB, pot / 8))
                if p_win < 0.75:
                    rais = int((12 * p_win - 5) * factor)
                else:
                    rais = int((-12 * p_win + 13) * factor)

                # Clamp and Round the raise amount
                min_r, max_r = current_state.raise_bounds
                rais = max(min_r, min(rais, max_r))
                rais = self._round_to_multiple(rais, 25)
                rais = max(min_r, min(rais, max_r)) # Re-clamp after rounding
                
                return ActionRaise(rais)
            elif current_state.can_act(ActionCall):
                return ActionCall()
            else:
                return ActionCheck()
                
        else:
            # Your Expected Value (EV) Max Call calculation
            max_call = int(p_win * pot)

            if current_state.can_act(ActionCheck):
                # Free to check: 20% bluff raise chance
                random_raise = random.randint(1, 10)
                if random_raise > 8 and current_state.can_act(ActionRaise):
                    min_r, max_r = current_state.raise_bounds
                    rais = min(max(max_call, min_r), max_r)
                    return ActionRaise(rais)
                else:
                    return ActionCheck()
                    
            else:
                # Facing a bet
                if max_call < cost:
                    return ActionFold()
                else:
                    # 20% bluff raise chance instead of just calling
                    random_raise = random.randint(1, 10)
                    if random_raise > 8 and current_state.can_act(ActionRaise):
                        min_r, max_r = current_state.raise_bounds
                        rais = min(max(max_call, min_r), max_r)
                        return ActionRaise(rais)
                    else:
                        return ActionCall()

if __name__ == '__main__':
    run_bot(Player(), parse_args())