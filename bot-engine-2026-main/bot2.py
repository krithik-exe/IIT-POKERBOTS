import eval7
import random

class Player(BaseBot):
    def __init__(self):
        # Load equity table
        self.preflop_equity = PREFLOP_EQUITY

        # Opponent modeling stats
        self.opp_fold_count = 0
        self.opp_raise_count = 0
        self.total_hands = 0
        self.tight_mode = False

        # --- REINFORCEMENT LEARNING PARAMETERS (FIX 4 APPLIED) ---
        self.q_table = {}
        self.alpha = 0.1
        self.epsilon = 0.15
        self.current_episode_history = []

    # ====================================
    # HAND START
    # ====================================
    def on_hand_start(self, game_info: GameInfo, current_state: PokerState):
        self.total_hands += 1
        # Enable tight mode if losing badly
        if game_info.bankroll < -200:
            self.tight_mode = True
        else:
            self.tight_mode = False

    # ====================================
    # HAND END — Learn opponent behavior
    # ====================================
    def on_hand_end(self, game_info: GameInfo, current_state: PokerState):
        # Track aggression
        if current_state.opp_wager > current_state.my_wager:
            self.opp_raise_count += 1
        if current_state.payoff > 0:
            self.opp_fold_count += 1

        # --- RL Q-TABLE UPDATE (FIX 4 APPLIED: No negative rewards for folding) ---
        reward = current_state.payoff 

        for state, action in self.current_episode_history:
            # If we folded, treat the reward as 0 so the bot doesn't think folding is strictly "bad"
            action_reward = 0 if action == 'Fold' else reward
            
            old_value = self.q_table.get(state, {}).get(action, 0.0)
            new_value = old_value + self.alpha * (action_reward - old_value)
            self.q_table[state][action] = new_value

        self.current_episode_history = []

    # ====================================
    # EQUITY & ODDS LOOKUP
    # ====================================
    def get_equity(self, my_cards):
        key = "".join(sorted(my_cards))
        return self.preflop_equity.get(key, 0.50)

    def get_pot_odds(self, current_state):
        cost = current_state.cost_to_call
        if cost == 0:
            return 0
        return cost / (current_state.pot + cost)

    # ====================================
    # RL STATE GENERATOR (FIX 2 APPLIED)
    # ====================================
    def get_rl_state(self, current_state):
        """Creates a smart state bucket looking at BOTH preflop odds and post-flop board."""
        preflop_eq = self.get_equity(current_state.my_hand)
        pot_odds = self.get_pot_odds(current_state)
        
        # Look at the community cards to see if we actually connected with the Flop!
        made_hand = "HighCard"
        try:
            if current_state.board:
                cards = [eval7.Card(c) for c in current_state.my_hand + current_state.board]
                val = eval7.evaluate(cards)
                made_hand = eval7.handtype(val) # e.g., "Pair", "Two Pair", "Flush"
        except:
            pass # Fallback just in case eval7 acts up
            
        eq_bucket = int(preflop_eq * 10) 
        odds_bucket = int(pot_odds * 10)
        
        # The Q-Table now understands the board! e.g., "eq:6_odds:2_hand:Pair"
        return f"eq:{eq_bucket}_odds:{odds_bucket}_hand:{made_hand}"

    # ====================================
    # AUCTION STRATEGY (FIX 1 APPLIED)
    # ====================================
    def auction_strategy(self, game_info, current_state):
        equity = self.get_equity(current_state.my_hand)

        # Polarized Bidding: Stop bleeding 2-4 chips. 
        # If we want it, we bid 20 (JARVIS's default). Otherwise, bid 0.
        if equity > 0.65:
            bid = min(20, current_state.my_chips, current_state.pot)
        else:
            bid = 0

        return ActionBid(bid)

    # ====================================
    # PREFLOP STRATEGY
    # ====================================
    def preflop_strategy(self, game_info, current_state):
        equity = self.get_equity(current_state.my_hand)
        pot_odds = self.get_pot_odds(current_state)

        equity_threshold = 0.60 if self.tight_mode else 0.50

        if equity > 0.65 and current_state.can_act(ActionRaise):
            min_raise, max_raise = current_state.raise_bounds
            raise_amt = min(min_raise + int(current_state.pot * 0.5), max_raise)
            return ActionRaise(raise_amt)

        if equity > pot_odds and equity > (equity_threshold - 0.10):
            if current_state.can_act(ActionCall):
                return ActionCall()
            if current_state.can_act(ActionCheck):
                return ActionCheck()

        if current_state.can_act(ActionCheck):
            return ActionCheck()
        return ActionFold()

    # ====================================
    # POSTFLOP STRATEGY (FIX 3 & 4 APPLIED)
    # ====================================
    def postflop_strategy(self, game_info, current_state):
        state = self.get_rl_state(current_state)
        
        if state not in self.q_table:
            self.q_table[state] = {'Fold': 0.0, 'Call': 0.0, 'Raise': 0.0}

        # --- EXPERT OVERRIDE (FIX 3 APPLIED) ---
        # Instead of instantly folding when seeing an Ace/King, we just force the bot 
        # to be more cautious and prefer checking/folding over raising.
        scary_card_seen = False
        if current_state.opp_revealed_cards:
            for card in current_state.opp_revealed_cards:
                if card[0] in ['A', 'K', 'Q']:
                    scary_card_seen = True

        # --- Q-LEARNING DECISION ---
        if random.random() < self.epsilon:
            action_name = random.choice(['Fold', 'Call', 'Raise'])
        else:
            q_values = self.q_table[state]
            action_name = max(q_values, key=q_values.get)

        # Force passive play if they revealed a scary card and our hand is weak
        if scary_card_seen and "Pair" not in state:
            action_name = 'Fold' if current_state.cost_to_call > 0 else 'Call'

        # Execute Action
        if action_name == 'Raise' and current_state.can_act(ActionRaise):
            min_raise, max_raise = current_state.raise_bounds
            self.current_episode_history.append((state, 'Raise'))
            return ActionRaise(min_raise)
            
        elif action_name == 'Call' and current_state.can_act(ActionCall):
            self.current_episode_history.append((state, 'Call'))
            return ActionCall()
            
        elif action_name in ['Call', 'Raise'] and current_state.can_act(ActionCheck):
            self.current_episode_history.append((state, 'Call'))
            return ActionCheck()
            
        else:
            self.current_episode_history.append((state, 'Fold'))
            if current_state.can_act(ActionCheck): return ActionCheck()
            return ActionFold()

    # ====================================
    # MAIN DECISION FUNCTION
    # ====================================
    def get_move(self, game_info: GameInfo, current_state: PokerState):
        street = current_state.street

        if street == 'auction':
            return self.auction_strategy(game_info, current_state)
        if street in ['pre-flop', 'preflop']:
            return self.preflop_strategy(game_info, current_state)
            
        return self.postflop_strategy(game_info, current_state)

# ====================================
# RUN BOT
# ====================================
if __name__ == '__main__':
    run_bot(Player(), parse_args())