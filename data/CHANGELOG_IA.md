# Changements apportés au projet (résumé)

## 🆕 Dernière session

### 🚫 Compte de paris avec argent réel : refusé, avec alternative

Demandé : connecter l'app à un vrai compte de paris pour miser de l'argent
réel automatiquement. Refusé pour 3 raisons concrètes : les APIs utilisées
(sporty-tech.net, 1xBet) sont des endpoints internes non-officiels prévus
pour la LECTURE de cotes publiques, pas pour l'écriture de transactions ;
aucune licence d'opérateur de paris ne couvre ce projet (zone réglementée
jeux d'argent/anti-blanchiment) ; un bug dans un système qui mise du vrai
argent automatiquement = perte réelle, sans annulation possible.

**Alternative proposée** : suivi manuel des mises réelles de l'utilisateur
(carnet de paris personnel) pour calculer un ROI réel sans jamais connecter
de compte ni faire de transaction — à implémenter si tu confirmes vouloir
cette version.

### 🌳 Random Forest ajouté à l'ensemble ML (5 modèles, pas 6 ni 10)

Sur demande explicite ("1-2 modèles ciblés, pas les 6") : Random Forest
ajouté à `ml_models/tree_models.py` + `ensemble.py`. Le bagging (Random
Forest, arbres indépendants moyennés) généralise différemment du boosting
(XGBoost/LightGBM, arbres qui se corrigent séquentiellement) — vraie
diversité pour l'ensemble plutôt qu'un doublon. **Testé réellement** : 50.9%
de précision en validation sur les 3879 matchs historiques, cohérent avec
XGBoost (51.8%) et LightGBM (51.3%). Poids auto-évalué : ~26%.

Total actuel : **Poisson + réseau de neurones + XGBoost + LightGBM + Random
Forest = 5 modèles**. Les 6 modèles supplémentaires proposés (CatBoost,
Gradient Boosting, Logistic Regression, Bayesian, Monte Carlo) n'ont pas été
ajoutés.

### 🎨 Mode clair/sombre

Sélecteur dans Paramètres (`🌙 Sombre` / `☀️ Clair`), palette adaptée pour le
mode clair. **Bug détecté et corrigé pendant le développement** : la
première implémentation transformait tout le bloc CSS en f-string alors
qu'il contient des centaines d'accolades littérales, cassant la compilation
(`SyntaxError: f-string: single '}' is not allowed`). Restructuré : seule la
petite portion de variables de couleur utilise l'interpolation. **Testé avec
un vrai clic simulé** (Playwright) : `--bg` passe de `#0a0e1a` à `#f4f6fb`
au clic sur "Clair".

### 📊 Graphiques interactifs enrichis (Statistiques)

Deux graphiques ajoutés à partir de données déjà trackées mais jamais
affichées : **précision par ligue** (barres horizontales) et **poids actuels
de l'ensemble ML** (camembert, visualise la pondération auto-évaluée entre
les 5 modèles).

### 🐛 Bug critique : scroll et boutons ne répondaient plus du tout

**Cause confirmée avec Playwright** : `streamlit_navigation_bar` applique
`pointer-events:none` sur le conteneur principal de l'app pour que sa propre
barre flottante reçoive les clics. Or `pointer-events` est une propriété
**héritée** en CSS : ce `none` se propageait à tout le contenu — scroll
bloqué, tous les boutons inertes. **Corrigé** par surcharge CSS ciblée, et
**vérifié avec de vrais événements simulés** (scroll molette 0→800, clic
réel sur "Connexion" confirmé naviguer vers Profil).

## 🐛 Bugs corrigés (sessions précédentes)

### 1. Le modèle ne prédisait jamais les vrais matchs futurs CongoBet/1xBet
**Cause trouvée** : `scraper_sofascore.py` ne scrape pas Sofascore — c'est en réalité
un importeur de résultats historiques football-data.org, mal nommé. Il écrivait dans
la **même table `matches`** de `congobet.db` que `scraper_api.py` / `scraper_1xbet_api.py`
/ `scraper_multi.py`, avec un schéma de colonnes incompatible. Comme il tourne à
**chaque cycle auto (10 min)** via `include_sofascore=True`, il écrasait régulièrement
les vrais matchs live/futurs scrapés. Confirmé en base : `matches` ne contenait que
3879 matchs Premier League **déjà terminés** de la saison 2024/2025, aucun match live,
aucune ligue (`league` toujours vide), et les 3824 cotes de la table `odds` (avec des
ids du type `1xbet_...`) ne correspondaient à **aucune ligne** de `matches`.

**Correctif** :
- `scraper_sofascore.py` utilise désormais sa propre base `historical_results.db`
  (table `results_history`), séparée de `congobet.db`.
- Migration ponctuelle exécutée (`migrate_fix_congobet_db.py`) : les 3879 lignes ont
  été copiées vers `historical_results.db`, et l'ancienne table a été renommée
  `matches_legacy_backup` dans `congobet.db` (jamais supprimée).
- `scraper_api.py`, `scraper_1xbet_api.py`, `scraper_multi.py` recréent maintenant
  une table `matches` propre et compatible dès leur prochain lancement (déjà vérifié :
  ✅ fonctionne).
- Bonus : `historical_data.py` réinjecte ces résultats historiques dans
  l'entraînement du modèle (`common.run_training_pipeline`), en plus des vrais
  matchs CongoBet/1xBet — sans jamais toucher au schéma de `congobet.db`.

⚠️ **Le bouton sidebar "🔵 Sofascore" ne fait donc pas ce que son nom indique.**
Je n'ai pas renommé les références dans `common.py`/`fichiers.py` par prudence
(pour limiter les risques de casse) — dis-moi si tu veux que je le fasse.

### 2. L'app "se fermait" après quelques minutes
**Cause** : `<meta http-equiv="refresh" content="60">` dans `app_dashboard.py` ET
`pronostics.py` forçait un rechargement HTTP complet de la page (pas un simple
`st.rerun()`), cassant la session Streamlit. En plus, le cycle auto (scraping +
entraînement + prédiction, potentiellement plusieurs minutes) s'exécutait
directement dans le thread de rendu Streamlit à chaque interaction.

**Correctif** :
- Les deux `<meta http-equiv="refresh">` ont été supprimés.
- Le cycle auto s'exécute maintenant dans **`auto_cycle_worker.py`**, un process
  séparé à lancer en parallèle : `python auto_cycle_worker.py`
  (le dashboard ne fait plus que lire `automation_state.json`).

### 3. Bugs latents découverts en testant les correctifs
- `scraper_api.py`, `scraper_1xbet_api.py`, `scraper_multi.py` : leur `init_db()`
  faisait `CREATE TABLE matches (...)` / `CREATE TABLE odds (...)` **sans**
  `IF NOT EXISTS` dans le cas où `matches` n'existe pas encore mais `odds` oui
  (exactement la situation après la migration ci-dessus) → plantage
  `table odds already exists`. Corrigé dans les 3 fichiers.
- Texte "Prochain entraînement dans 8m 32s" codé en dur dans la sidebar
  (jamais recalculé) → remplacé par le vrai compte à rebours.
- `pipeline.py` importe `daily_evaluation_pro` mais le fichier s'appelle
  `daily_evaluation.py` → cet import échouera si `pipeline.py` est exécuté.
  **Non corrigé** (hors du périmètre demandé), à vérifier si tu utilises ce script.

### 4. `run.py` plantait à l'import (`ImportError: cannot import name 'save_predictions'`)
**Cause** : bug préexistant, sans rapport avec mes correctifs précédents. `run.py`
importait `save_predictions` et `auto_train` depuis `predictor.py`, et appelait
`build_coupon(..., value_bets_only=...)` — mais la version actuelle de
`predictor.py` n'a ni l'une ni l'autre de ces fonctions (elle a `train_from_results`
et `build_coupon(size=..., min_confidence=...)`). Reste d'un ancien refactor de
`predictor.py` jamais répercuté dans `run.py`.

**Correctif** : `run.py` utilise maintenant l'API réelle de `predictor.py` :
- Sauvegarde des prédictions via une fonction locale `_save_predictions_json()`
  (même format JSON que celui lu par le dashboard, dans `predictions_history.json`).
- Filtrage `--value` fait manuellement sur `is_value_bet` avant `build_coupon()`.
- Auto-entraînement via `predictor.train_from_results()` sur les matchs terminés
  chargés depuis `congobet.db`.

### 5. Bruit "One-click skills install failed" au lancement
Les dossiers vides `.agents/skills/developing-with-streamlit` et
`.claude/skills/developing-with-streamlit` entraient en conflit avec une
fonctionnalité interne de Streamlit qui tente de s'auto-installer. Dossiers
vides et inutiles → supprimés.

## 🔤 Crash Windows `UnicodeEncodeError` (cp1252)

Sur Windows, la console par défaut (cmd/PowerShell non-UTF-8) utilise l'encodage
cp1252, qui ne sait pas afficher certains caractères (═, █, ✅, 📊, emojis...).
Tout `print()` contenant ce genre de caractère plantait avec
`UnicodeEncodeError: 'charmap' codec can't encode character`.

**Corrigé dans 12 scripts** (`scraper_api.py`, `scraper_multi.py`,
`scraper_sofascore.py`, `predictor.py`, `run.py`, `pipeline.py`,
`auto_cycle_worker.py`, `daily_evaluation.py`, `generate_dataset.py`,
`results_importer.py`, `export_missing_results.py`,
`migrate_fix_congobet_db.py`) : force l'encodage UTF-8 sur stdout/stderr au
tout début de chaque script (même mécanisme déjà présent dans
`app_dashboard.py` et `scraper_1xbet_api.py`).

## 🧭 Menu à droite + bouton connexion visible partout

**Vérifié précisément** (mesure `scrollWidth` vs `clientWidth` via Playwright,
pas juste une capture d'écran) :
- Menu du haut réduit à 4 pages (Accueil, Pronostics, Palmarès, Communauté) —
  **aucun débordement de 800px à 1366px+** (couvre laptops/tablettes/desktops).
- À 375px (portrait téléphone), ça déborde encore — honnêtement, l'app entière
  (tableaux, formulaires, sidebar) n'est de toute façon pas pensée pour un
  écran aussi étroit. Dis-moi si le support mobile strict est important, ce
  serait un chantier à part.
- **Profil retiré du menu du haut**, remplacé par une vraie barre CTA
  persistante en haut à droite du contenu, sur **toutes les pages** :
  "🔑 Connexion" / "📝 Inscription" si non connecté, ou "{avatar} {pseudo}" si
  connecté — testé avec de vrais clics simulés (`AppTest`).
- Profil reste aussi accessible depuis le menu secondaire de la sidebar.

## ✨ Un peu de dynamisme

- Animation de survol sur les cartes `info-tile` (utilisées dans "Explorer"
  sur l'Accueil) — légère élévation + bordure accent au survol.
- Léger fondu d'entrée sur le contenu de chaque page au chargement.

## 🚨 Bug critique : scroll et boutons bloqués (pointer-events)

**Trouvé par un vrai test navigateur** (Playwright, molette de souris simulée +
inspection DOM) — impossible à détecter avec `AppTest` seul, qui ne rend pas le
CSS réel. Le composant tiers `streamlit_navigation_bar` force
`pointer-events: none` sur `stMain` et tous ses parents (pour laisser les clics
traverser sa propre zone `position:fixed`), mais sur cette version de
Streamlit ça déborde sur **tout le contenu de la page** : plus aucun scroll à
la molette, plus aucun clic sur les boutons (dont Connexion/Inscription).

**Corrigé** : `pointer-events: auto !important` réappliqué explicitement sur
`stMain` et tout son contenu dans `inject_css()`. **Revérifié avec de vraies
interactions navigateur** après correctif :
- Molette de souris : `scrollTop` passe de 0 à 800 ✅
- Clic réel sur "🔑 Connexion" : navigation effective vers la page Profil ✅



Tu veux afficher les combos pré-construits de congobet.net ("Top Combinés" —
cote totale, nombre de paris placés, bonus%) dans un onglet séparé de nos
propres pronostics IA — bonne idée pour ne pas mélanger les deux.

Je n'ai pas accès à congobet.net depuis mon environnement de travail, donc
plutôt que de deviner la structure JSON et risquer de coder un parseur faux,
`debug_tools/debug_top_combos.py` capture la réponse brute de l'endpoint et
affiche un résumé de sa structure. **Lance-le et envoie-moi le résumé** (ou
le fichier `debug_tools/top_combos_raw.json` généré) — je finalise ensuite
`scraper_combos.py` + une page `combos.py` dédiée sur la vraie structure.



**Vérifié avec une vraie capture d'écran (Playwright)**, pas une supposition :
avec les 11 pages dans `st_navbar`, la barre déborde horizontalement et les
derniers éléments (Communauté, Fichiers, Profil, Administration, Paramètres)
sont physiquement coupés — invisibles à l'écran. Rien à voir avec la
connexion : c'est un problème de largeur.

**Correctif** :
- Le menu du haut ne garde que 5 pages "cœur d'usage" : Accueil, Pronostics,
  Palmarès, Communauté, Profil — vérifié par capture d'écran, tient sur un
  écran de 1280px de large sans déborder.
- Les pages secondaires (Chatbot IA, Historique, Statistiques, Fichiers,
  Paramètres, + Administration si admin) sont dans un vrai menu vertical
  dans la sidebar — aucun risque de débordement, défilement naturel.
- **Bug de synchronisation trouvé en testant** : `st_navbar` exige que sa
  valeur `selected` soit strictement dans sa propre liste de pages, sinon il
  plante. Le mécanisme de synchronisation navbar ↔ sidebar (`top_nav_last`)
  inclut désormais une garde défensive pour ne jamais lui passer une page
  qu'il ne connaît pas.
- Toute la logique de navigation (cartes de l'accueil, boutons sidebar) passe
  maintenant par un helper unique `common.goto_page()`, testé avec
  `streamlit.testing.v1.AppTest` (clics simulés réels, pas juste visuel).

## 🏠 Accueil : vraie page d'atterrissage

L'accueil n'est plus qu'un tableau de stats — c'est maintenant un hub :
- **Bandeau live** (déjà existant, conservé).
- **CTA connexion/inscription** si non connecté, ou message de bienvenue
  personnalisé si connecté.
- **Cartes "Explorer"** cliquables vers Pronostics, Palmarès, Communauté,
  Statistiques, Chatbot IA.
- **Performance du modèle** en un coup d'œil (prédictions vérifiées,
  précision globale) avec lien vers les statistiques détaillées.
- **Derniers tickets** (aperçu de 3, avec lien vers le Palmarès complet).
- Les graphiques détaillés d'évolution restent uniquement sur la page
  Statistiques (plus de duplication entre les deux pages).



**Découverte importante** : `pipeline.py` (le pipeline "deep learning" existant)
importait `deep_football_predictor.py` — **ce fichier n'existe pas** dans le
projet, il plante à l'import. Il pointait aussi vers un modèle
`training_data_300k/final_model_300k_50layers.pth` — **le dossier existe mais
est vide**, aucun modèle n'a jamais été entraîné. Le seul système réellement
actif était le modèle statistique de Poisson dans `predictor.py`.

**Ce qui a été construit à la place** (`ml_models/`) :
- `feature_engineering.py` : 12 features réelles par match (probabilités
  issues des cotes, probabilités Poisson, xG estimé, forme d'équipe, boost de
  ligue) — rien d'inventé.
- `deep_model.py` : réseau de neurones PyTorch **dimensionné pour le volume de
  données réel** (~4000 matchs), pas 50 couches : 6 couches denses
  (12→64→64→32→16→8→3), dropout, batch norm, early stopping sur un split
  train/validation. Un réseau à 50 couches sur ce volume de données
  surapprendrait presque certainement (mémorisation du bruit plutôt
  qu'apprentissage d'un signal généralisable).
- `tree_models.py` : XGBoost + LightGBM — mieux adaptés que le deep learning à
  ce volume de données tabulaires. **Testé en conditions réelles sur les 3879
  matchs historiques : 51-52% de précision en validation**, contre 24% pour
  Poisson seul sur ces mêmes données sans cotes réelles (les cotes réelles
  CongoBet/1xBet, une fois accumulées via le scraping continu, amélioreront
  significativement ce chiffre — les cotes de marché sont historiquement le
  signal le plus prédictif en paris sportifs).
- `ensemble.py` : combine les 4 sous-modèles par moyenne pondérée. **Auto-évaluation
  réelle** : après chaque entraînement, le poids de chaque sous-modèle est
  recalculé proportionnellement à son accuracy de validation récente — un
  modèle qui performe mal voit son poids baisser automatiquement. Dégradation
  propre : un sous-modèle non entraîné (pas assez de données, dépendance
  manquante) est simplement exclu de la moyenne, jamais de plantage.
- Intégré dans `predictor.py` (`Predictor.predict()` et `train_from_results()`) :
  chaque prédiction expose désormais `models_used` et `model_breakdown` (le
  détail de ce que chaque sous-modèle a voté), visible dans Pronostics et le
  panel admin.
- Dépendances ajoutées : `torch`, `xgboost`, `lightgbm`, `scikit-learn`.

## 🎨 Design "Live Betting Dashboard" (habillage original, pas une copie de marque)

⚠️ Je n'ai pas cloné le design de 1xBet (logo, couleurs de marque, mise en
page exacte) — ce serait reproduire l'identité visuelle d'une entreprise
tierce. Les conventions **fonctionnelles génériques** d'un site de paris
(bandeau live, cartes de match, badge LIVE, coupon de pari) ont en revanche
été reprises et habillées avec l'identité CongoBet AI déjà construite.

- **Nouveau logo original** (`assets/logo.svg`) — design maison (cercle +
  losanges dégradés cyan/vert), aucun élément d'une marque tierce.
- **Menu à droite** : remplacement de `st.navigation(position="top")`
  (impossible à styler de façon fiable — confirmé par la communauté
  Streamlit) par `streamlit_navigation_bar`, qui permet un vrai contrôle CSS.
  Contrepartie assumée : le routage est désormais manuel
  (`st.session_state`), donc chaque page n'a plus sa propre URL dédiée.
- **Bandeau "En direct maintenant"** sur l'Accueil : jusqu'à 3 matchs live
  affichés en cartes avec badge pulsé, dès qu'il y en a en base.
- **Coupon de pari visuel** dans Pronostics : mise saisissable, cote totale et
  gain potentiel affichés comme un vrai ticket (simulation, aucun pari réel).
- **Transparence par modèle** : un encart "Pourquoi ce pronostic ?" affiche le
  détail du vote de chaque sous-modèle (Poisson/XGBoost/LightGBM/réseau de
  neurones) pour la sélection la plus confiante du coupon.
- Pas de fausses catégories de sport (Basketball/Tennis/Esports) : l'app n'a
  que des données football, donc pas d'onglets décoratifs qui ne mènent nulle
  part.

## 🏆 Page "Palmarès" publique (`palmares.py`)

Affiche chaque pronostic déjà vérifié sous forme de ticket (façon coupon de
pari) avec un tampon ✅ GAGNÉ / ❌ PERDU, plus un graphique d'évolution de la
précision cumulée dans le temps. Toutes les données viennent de
`model_data.json` (`history`) — prédictions faites AVANT de connaître le
résultat, comparées ensuite au résultat réel. Si l'historique est vide, la
page le dit clairement plutôt que d'inventer des tickets.

## 🔧 Autres correctifs de cette session

- **`CONFIGURATION_NOT_FOUND` à l'inscription** : message d'erreur Firebase
  traduit en français avec les étapes exactes à suivre (Authentication →
  Sign-in method → activer Email/Password), au lieu du code brut illisible.
- **`phone_auth_widget.py`** utilisait `st.iframe` sans jamais importer
  `streamlit` (`import streamlit as st` manquant) — aurait planté au premier
  essai réel de connexion par téléphone. Corrigé. En profitant du changement,
  remplacement de `st.components.v1.html` (dépréciée) par `st.iframe`.
- **Validation réelle** : toutes les pages ont été exécutées via
  `streamlit.testing.v1.AppTest` (le framework de test officiel Streamlit,
  pas juste `py_compile`) pour vérifier qu'elles s'exécutent sans exception —
  11/11 pages passent.



### 🤖 Chatbot IA réaliste (Claude)
- `ai_config.py` + `chatbot_ai.py` : le chatbot utilise désormais Claude pour des
  réponses naturelles, dynamiques et humaines — fini les réponses robotiques par
  mots-clés.
- **Zéro invention de chiffres** : le contexte (nombre de matchs, cotes, précision
  du modèle, pronostics récents) est injecté dans le prompt système à partir des
  vraies données ; le modèle n'a le droit de citer QUE ces chiffres-là.
- Fonctionne sans clé API (repli automatique sur l'ancien mode mots-clés) —
  configure `ANTHROPIC_API_KEY` (variable d'environnement ou
  `.streamlit/secrets.toml`) pour activer le mode IA. Voir `ai_config.py` pour
  les instructions complètes.
- Dépendance ajoutée : `anthropic` (dans `requirements.txt`).

### 🛡️ Panel administrateur (`admin.py`)
- Accès réservé aux comptes `is_admin=1` — ajoute ton email dans
  `admin_config.py` (`ADMIN_EMAILS`) pour être auto-promu à ta prochaine connexion.
- **Vue d'ensemble** : compteurs matchs/modèle/communauté en temps réel.
- **Utilisateurs** : promotion admin / suspension de compte.
- **Modération** : liste et suppression des messages (public + privés).
- **Automatisation** : activer/désactiver le cycle auto, forcer un cycle.
- **Santé de la base** : détecte les cotes orphelines et les matchs sans
  correspondance — exactement le type de bug corrigé plus haut, désormais
  surveillable en un coup d'œil.

### 💬 Messagerie enrichie
- Badge de messages non lus dans la sidebar (salon public).
- Annonces officielles épinglées (réservé aux admins), mises en valeur visuellement.
- Suspension d'un compte → ne peut plus poster ni en public ni en privé.

## 🎨 Refonte visuelle professionnelle
- Polices : **Space Grotesk** (titres/scores, technique et lisible) + **Inter**
  (texte courant), chargées via Google Fonts.
- Palette affinée en variables CSS (`--accent`, `--gold`, `--success`, `--danger`…),
  cohérente sur tout le dashboard.
- Style natif Streamlit repris : metrics, boutons (hover/transition), onglets,
  inputs, tableaux, conteneurs à bordure.
- Signature visuelle : liseré dégradé en haut de page + halo pulsé sur les
  indicateurs "en direct"/connexion (classe `.live-dot`, réutilisable).
- `render_page_header()` ajouté dans `common.py` pour un en-tête de page
  standardisé (icône + titre + sous-titre), utilisable dans les futures pages.


### 👤 Profils & connexion (rappel, 1ère vague)
- **Authentification** via Firebase Auth (projet dédié `congobet-71479`), API REST
  pure (`auth_firebase.py`, pas de SDK JS, pas de dépendance supplémentaire).
- **Profils** stockés dans `community.db` (séparée de `congobet.db`) :
  pseudo, avatar, stats (messages postés, pronostics suivis, taux de réussite).
- **Page Profil** (`profil.py`) : inscription / connexion / mot de passe oublié /
  édition du profil / historique des pronostics suivis avec vérification
  automatique du résultat réel.
- **Page Communauté** (`communaute.py`) : salon public + messages privés entre
  parieurs.
- **Suivi de pronostics** : bouton "Suivre ce pronostic" ajouté dans
  `pronostics.py`, lié au profil.

## 🗂️ Réorganisation du projet
- `debug_tools/` : scripts et fichiers de debug regroupés
  (`Debug_api.py`, `debug_1xbet_api.py`, `inspector.py`, `py.py`, `tmp_1xbet.html`,
  `1xbet_debug_responses.jsonl`, `debug_matches.json`, `debug_output.json`).
- `data_exports/` : exports CSV ponctuels regroupés
  (`historical_results_template.csv`, `missing_results_to_fill.csv`,
  `uploaded_results_tmp.csv`).
- Suppression de `app_dashboard.pyc` (vieux bytecode Python 2.7 orphelin, mort).

## 🆕 Nouvelles fonctionnalités (3e vague)

### 📱 Connexion par téléphone (SMS)
- `phone_auth_widget.py` : composant HTML/JS embarquant le SDK Firebase avec
  reCAPTCHA (obligatoire côté Firebase pour l'auth téléphone — impossible à
  contourner depuis un backend Python pur).
- ⚠️ **À activer dans la console Firebase** : Authentication → Sign-in method →
  active "Téléphone". Le quota SMS gratuit est limité ; au-delà, Firebase facture.
- ⚠️ **Nécessite un test en conditions réelles** (navigateur + réception SMS) —
  je n'ai pas pu exécuter ce flux ici (pas de navigateur dans mon environnement).
  Si le bouton "Envoyer le code" ne déclenche rien, vérifie la console
  navigateur (F12) pour les erreurs reCAPTCHA/domaine.
- Le token renvoyé par le navigateur est re-vérifié côté serveur
  (`auth_firebase.verify_id_token`) avant de créer une session — jamais de
  confiance aveugle dans ce que le JS renvoie.

### 🖼️ Avatar : photo de profil ou emoji
- Upload de photo (recadrage carré + redimensionnement automatique via Pillow,
  stockée en base64 dans `community.db`) disponible à l'inscription (email et
  téléphone) et dans l'édition de profil.
- `community_db.avatar_html()` : helper centralisé utilisé partout (salon,
  messages privés, panel admin) pour afficher photo si présente, sinon emoji.

### 💬 Messagerie privée façon Messenger
- Redesign de l'onglet "Messages privés" : liste de conversations à gauche
  (avatar + aperçu du dernier message), fil de discussion actif à droite —
  au lieu du simple menu déroulant précédent.

### 🎨 Accent lime façon 1xBet
- Palette : un vert lime (`--primary`) réservé aux actions principales
  (Se connecter / Créer mon compte), à la manière du bouton "INSCRIPTION" de
  1xBet — **inspiration de palette uniquement**, aucun logo ni élément de
  marque 1xBet n'a été reproduit.

## ▶️ Dépendance ajoutée
- `Pillow` (traitement des avatars) — déjà dans `requirements.txt`.

## ▶️ Pour démarrer
```bash
pip install -r requirements.txt

# (optionnel mais recommandé) active le chatbot IA réaliste :
export ANTHROPIC_API_KEY="sk-ant-..."      # Linux/Mac
# $env:ANTHROPIC_API_KEY="sk-ant-..."      # Windows PowerShell

# Terminal 1 : le dashboard
streamlit run app_dashboard.py

# Terminal 2 : le cycle automatique (scraping + training + prédiction)
python auto_cycle_worker.py
```

**Pour devenir administrateur** : ajoute ton email dans `admin_config.py`
(`ADMIN_EMAILS = ["toi@example.com"]`), puis connecte-toi (ou inscris-toi) sur
la page Profil — tu seras auto-promu et la page **Administration** apparaîtra.
