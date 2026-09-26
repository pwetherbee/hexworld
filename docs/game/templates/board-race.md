# Template: Board race (The Game of Life and friends)

Status: **later**. A short, social, turn-based game where each player moves a piece through the
world toward an objective, and the places they land on shape their journey.

Inspirations: The Game of Life (life-path choices and events), Heat: Pedal to the Metal (cards
instead of dice, terrain limits), Tokaido (a road with stops, each giving a different kind of
points), Jaipur/Snakes & Ladders as anti-models (no decisions), Mario Party (events and mini-games on
spaces).

---

## 1. The fantasy

You and your friends travel the same world from its start to its goal, each choosing a different
path and a different life along the way. The board is the generated world; every space is a real
place with a reason to stop.

## 2. The board

- A **track** is extracted from the world: the director picks a start and a goal and lays a network
  of 25–60 spaces along roads, rivers and passable tiles, with 2–4 forks (short and risky vs long and
  safe). The track is drawn on the map as a path layer.
- Each space has a **type** derived from its tile: town (shop, career), wild (event), landmark (big
  moment), hazard (lose time), crossroads (choose).

## 3. Core turn

```
play a movement card (or roll, by option) → move → resolve the space
  → choose (buy, take a job, help someone, gamble) → end turn
```

- **Movement cards, not dice** (Heat): each player has a small hand of movement values, refilled
  from a deck, so movement is a decision, not luck. A "roll" option exists for family play.
- Spaces offer **choices with trade-offs** (Game of Life's careers, houses, kids become
  world-specific: an apprenticeship with the lighthouse keeper, a stake in a fishing boat).
- Scoring in 3–4 currencies that the world defines (coins, renown, friends, memories), converted at
  the end with **set-collection bonuses** (Tokaido), so different paths can win.

## 4. Generated content

- The track, spaces and their events (grounded in each tile's place and the bible).
- Careers, possessions and life events in the world's idiom, each mapped to a designed effect card.
- A **narrator** writes one-line recaps per turn and a short "life story" per player at the end.

## 5. Dynamic

- Events evolve during the game: a storm closes a fork, a festival moves into a town, a rival's
  earlier choice changes a space ("the bakery you bought now sells to everyone who lands here").

## 6. Players

- 1–6, hot-seat first, AI opponents with personalities (the same bots used for playtesting).
- 20–40 minutes.

## 7. Open questions

- Cards vs dice as the default?
- Should players' choices change the board for everyone (more interaction) or only for themselves?
