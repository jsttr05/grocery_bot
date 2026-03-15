WS_URL = "wss://game.ainm.no/ws?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiIwM2VjOGE5Mi02NGM4LTRmZWMtODY1OS1hYjRjYzk2NTBhOGQiLCJ0ZWFtX2lkIjoiMmMxMGRjOTEtNTU0NC00MWMzLTkxNDctMDk1NjE2MmE0MDdkIiwibWFwX2lkIjoiMTIwYzUxZGEtYzc2NS00YmFiLThiNzktYmJhOTQ1YTU5ZTdjIiwibWFwX3NlZWQiOjcwMDUsImRpZmZpY3VsdHkiOiJuaWdodG1hcmUiLCJleHAiOjE3NzM1ODk2MDF9.drjh0BvhfpojceBDGuv8UcyCy78wM7Zr1MiWKdzPkSw"

STRATEGY_EASY = "easy"
STRATEGY_MEDIUM = "medium"
STRATEGY_HARD = "hard"
STRATEGY_NIGHTMARE = "nightmare"

DEFAULT_STRATEGY = STRATEGY_NIGHTMARE

# Delivery action name differs by server/difficulty.
# Easy/medium/hard use "drop_off"; nightmare uses "submit".
DELIVER_ACTIONS: dict[str, str] = {
    STRATEGY_EASY: "drop_off",
    STRATEGY_MEDIUM: "drop_off",
    STRATEGY_HARD: "drop_off",
    STRATEGY_NIGHTMARE: "drop_off",
}
