"""
admin_config.py — Qui a accès au panel administrateur
===========================================================
Ajoute ton email ici pour être automatiquement promu administrateur lors de
ta prochaine connexion (ou inscription). Tu pourras ensuite promouvoir
d'autres utilisateurs directement depuis le panel admin.

⚠️ Je ne peux pas créer un compte à ta place : je n'ai pas accès à ton
projet Firebase depuis mon environnement (aucun identifiant, aucune API).
Ce que je peux faire : préparer l'email pour qu'il devienne admin
AUTOMATIQUEMENT dès que TU t'inscris avec, via le vrai formulaire
d'Inscription de l'app (page Profil → onglet Inscription).

COMPTE ADMIN SUGGÉRÉ (à utiliser dans le formulaire d'Inscription réel) :
  Email    : admin@congobet.ai
  Mot de passe : choisis-en un toi-même (6 caractères min.), je ne peux pas
                 le définir à ta place — Firebase ne permet pas de créer un
                 compte sans mot de passe choisi par la personne qui s'inscrit.

Une fois inscrit avec cet email exact, tu seras automatiquement administrateur
(voir community_db.create_user_profile / sync_admin_status).
"""

ADMIN_EMAILS = [
    "admin@congobet.ai",
]
