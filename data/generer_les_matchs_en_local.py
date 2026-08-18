import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta

n = 1000000
rng = np.random.default_rng(42)

teams = [f"T{i:03d}" for i in range(1, 501)]
competitions = [f"C{i:02d}" for i in range(1, 61)]
start_date = datetime(2023, 1, 1)
end_date = datetime(2026, 7, 10)
span = (end_date - start_date).days

home = rng.choice(teams, size=n)
away = np.array([rng.choice([t for t in teams if t != h]) for h in home])

dates = [start_date + timedelta(days=int(x)) for x in rng.integers(0, span, size=n)]
season = [f"{d.year-1}-{d.year}" if d.month < 7 else f"{d.year}-{d.year+1}" for d in dates]

hg = np.clip(rng.poisson(1.45, size=n), 0, 8)
ag = np.clip(rng.poisson(1.20, size=n), 0, 8)
result = np.where(hg > ag, "H", np.where(hg < ag, "A", "D"))

df = pd.DataFrame({
    "match_id": np.arange(1, n + 1),
    "date": [d.strftime("%Y-%m-%d") for d in dates],
    "season": season,
    "competition": rng.choice(competitions, size=n),
    "home_team": home,
    "away_team": away,
    "home_goals": hg,
    "away_goals": ag,
    "result": result,
    "shots_home": rng.integers(3, 26, size=n),
    "shots_away": rng.integers(3, 26, size=n),
    "shots_on_target_home": rng.integers(0, 12, size=n),
    "shots_on_target_away": rng.integers(0, 12, size=n),
    "possession_home_pct": rng.integers(35, 66, size=n),
    "corners_home": rng.integers(0, 13, size=n),
    "corners_away": rng.integers(0, 13, size=n),
    "yellow_cards_home": rng.integers(0, 6, size=n),
    "yellow_cards_away": rng.integers(0, 6, size=n),
    "red_cards_home": rng.choice([0, 0, 0, 1], size=n),
    "red_cards_away": rng.choice([0, 0, 0, 1], size=n),
})

os.makedirs("output", exist_ok=True)
path = "output/football_matches_100000.csv"
df.to_csv(path, index=False)

print(f"Fichier créé: {path}")
print(f"Lignes: {len(df)}")
print(f"Taille: {os.path.getsize(path) / 1024 / 1024:.2f} Mo")