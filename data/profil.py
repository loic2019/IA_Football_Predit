"""
profil.py — Inscription, connexion et profil du parieur
================================================================
Authentification par EMAIL (mot de passe, via Firebase Auth REST) ou par
TÉLÉPHONE (SMS, via un composant JS embarqué — voir phone_auth_widget.py).
Avatar : emoji au choix, ou photo uploadée (redimensionnée et stockée en
base64 dans community.db).
"""

import base64
import io

import streamlit as st
from PIL import Image

import auth_firebase
import community_db
from ai_config import ASSISTANT_NAME  # noqa: F401 (réservé pour usage futur)
from phone_auth_widget import render_phone_auth_widget


AVATAR_CHOICES = ["⚽", "🎯", "🔥", "🍀", "🦁", "🐺", "🐍", "🚀", "👑", "🎲"]
MAX_AVATAR_DIMENSION = 256


def _is_logged_in() -> bool:
    return bool(st.session_state.get("auth_user"))


def _process_avatar_upload(uploaded_file) -> str:
    """Redimensionne et encode une photo uploadée en base64 (JPEG, carré, léger)."""
    image = Image.open(uploaded_file)
    image = image.convert("RGB")

    # Recadrage carré centré puis redimensionnement
    w, h = image.size
    side = min(w, h)
    left, top = (w - side) // 2, (h - side) // 2
    image = image.crop((left, top, left + side, top + side))
    image = image.resize((MAX_AVATAR_DIMENSION, MAX_AVATAR_DIMENSION))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _do_login(email: str, password: str):
    ok, data = auth_firebase.sign_in(email, password)
    if not ok:
        st.error(f"❌ Connexion impossible : {data.get('error')}")
        return
    _finalize_session(data["localId"], email=email, id_token=data.get("idToken"), refresh_token=data.get("refreshToken"))


def _do_signup(email: str, password: str, pseudo: str, avatar_emoji: str, avatar_image_b64: str = None):
    pseudo = (pseudo or "").strip()
    if not pseudo:
        st.error("❌ Choisis un pseudo.")
        return
    if community_db.pseudo_taken(pseudo):
        st.error("❌ Ce pseudo est déjà pris, choisis-en un autre.")
        return

    ok, data = auth_firebase.sign_up(email, password, display_name=pseudo)
    if not ok:
        st.error(f"❌ Inscription impossible : {data.get('error')}")
        return

    uid = data["localId"]
    profile = community_db.create_user_profile(uid, email, pseudo, avatar_emoji, avatar_image_b64=avatar_image_b64)

    st.session_state.auth_user = {
        "uid": uid, "email": email,
        "id_token": data.get("idToken"), "refresh_token": data.get("refreshToken"),
    }
    st.session_state.user_profile = profile
    st.success(f"✅ Compte créé, bienvenue {pseudo} !")
    st.rerun()


def _finalize_session(uid: str, email: str = "", phone: str = "", id_token: str = None, refresh_token: str = None):
    """Termine la connexion : retrouve/crée le profil local, vérifie le ban, ouvre la session."""
    profile = community_db.get_user_by_uid(uid)
    if not profile:
        st.session_state["_pending_new_user"] = {"uid": uid, "email": email, "phone": phone}
        st.rerun()  # sans ça, rien ne s'affiche tant qu'aucun autre widget ne redéclenche un rerun
        return  # profil.py affichera un petit formulaire "choisis ton pseudo"

    community_db.sync_admin_status(profile["id"], email)
    profile = community_db.get_user_by_id(profile["id"])

    if profile.get("is_banned"):
        st.error("🚫 Ce compte a été suspendu. Contacte un administrateur.")
        return

    st.session_state.auth_user = {"uid": uid, "email": email or profile.get("email", ""), "id_token": id_token, "refresh_token": refresh_token}
    st.session_state.user_profile = profile
    st.success(f"✅ Bienvenue {profile['pseudo']} !")
    st.rerun()


def _handle_phone_auth_result(result: dict | None):
    """Traite la valeur renvoyée par le composant (voir phone_auth_widget.py).
    Remplace l'ancien mécanisme par query_params, cassé par le sandbox des
    iframes Streamlit (voir le docstring de phone_auth_widget.py)."""
    if not result or not result.get("idToken"):
        return

    ok, user_data = auth_firebase.verify_id_token(result["idToken"])
    if not ok:
        st.error(f"❌ Connexion par téléphone impossible : {user_data.get('error')}")
        return

    uid = user_data.get("localId")
    real_phone = user_data.get("phoneNumber", result.get("phoneNumber"))
    _finalize_session(uid, phone=real_phone)


def _render_pending_new_user_form():
    """Après une 1ère connexion par téléphone : demande juste un pseudo pour créer le profil local."""
    pending = st.session_state["_pending_new_user"]
    st.info(f"📱 Numéro vérifié : {pending['phone']}. Choisis un pseudo pour finaliser ton inscription.")

    with st.form("pending_pseudo_form"):
        pseudo = st.text_input("Pseudo")
        avatar = st.selectbox("Avatar", AVATAR_CHOICES)
        photo = st.file_uploader("Ou une photo de profil (facultatif)", type=["png", "jpg", "jpeg"])
        submitted = st.form_submit_button("Valider", width="stretch", type="primary")
        if submitted:
            pseudo = pseudo.strip()
            if not pseudo:
                st.error("❌ Choisis un pseudo.")
            elif community_db.pseudo_taken(pseudo):
                st.error("❌ Ce pseudo est déjà pris.")
            else:
                avatar_b64 = _process_avatar_upload(photo) if photo else None
                profile = community_db.create_user_profile(
                    pending["uid"], pending.get("email", ""), pseudo, avatar,
                    phone=pending.get("phone"), avatar_image_b64=avatar_b64,
                )
                st.session_state.auth_user = {"uid": pending["uid"], "email": pending.get("email", ""), "id_token": None, "refresh_token": None}
                st.session_state.user_profile = profile
                del st.session_state["_pending_new_user"]
                st.success(f"✅ Bienvenue {pseudo} !")
                st.rerun()


def _do_logout():
    st.session_state.auth_user = None
    st.session_state.user_profile = None
    st.rerun()


def render_login_signup():
    st.title("👤 Connexion / Inscription")
    st.caption("Connecte-toi pour suivre tes pronostics, voir tes stats et discuter avec les autres parieurs.")

    # Un compte Firebase valide mais sans profil local (pseudo/avatar) doit
    # d'abord passer par ce petit formulaire — quel que soit le mode de
    # connexion utilisé (email ou téléphone). Avant ce correctif, ce cas
    # n'était géré que pour la connexion par téléphone : côté email, la
    # connexion réussissait bien côté Firebase mais rien ne s'affichait.
    if "_pending_new_user" in st.session_state:
        _render_pending_new_user_form()
        return

    tab_login, tab_signup, tab_phone, tab_forgot = st.tabs(
        ["🔑 Connexion", "📝 Inscription", "📱 Téléphone", "❓ Mot de passe oublié"]
    )

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Mot de passe", type="password", key="login_password")
            submitted = st.form_submit_button("Se connecter", width="stretch", type="primary")
            if submitted:
                if not email or not password:
                    st.error("❌ Merci de remplir email et mot de passe.")
                else:
                    _do_login(email, password)

    with tab_signup:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            pseudo = st.text_input("Pseudo (visible par les autres parieurs)", key="signup_pseudo")
            col_a, col_b = st.columns(2)
            with col_a:
                avatar = st.selectbox("Avatar (emoji)", AVATAR_CHOICES, key="signup_avatar")
            with col_b:
                photo = st.file_uploader("Ou une photo (facultatif)", type=["png", "jpg", "jpeg"], key="signup_photo")
            password = st.text_input("Mot de passe (6 caractères min.)", type="password", key="signup_password")
            password2 = st.text_input("Confirmer le mot de passe", type="password", key="signup_password2")
            submitted = st.form_submit_button("Créer mon compte", width="stretch", type="primary")
            if submitted:
                if not email or not password or not pseudo:
                    st.error("❌ Merci de remplir tous les champs.")
                elif password != password2:
                    st.error("❌ Les mots de passe ne correspondent pas.")
                else:
                    avatar_b64 = _process_avatar_upload(photo) if photo else None
                    _do_signup(email, password, pseudo, avatar, avatar_image_b64=avatar_b64)

    with tab_phone:
        st.caption(
            "Reçois un code par SMS pour te connecter ou t'inscrire — aucun mot de passe nécessaire. "
            "⚠️ Nécessite que l'auth par téléphone soit activée côté Firebase (voir phone_auth_widget.py)."
        )
        phone_result = render_phone_auth_widget()
        _handle_phone_auth_result(phone_result)

    with tab_forgot:
        with st.form("forgot_form"):
            email = st.text_input("Ton email", key="forgot_email")
            submitted = st.form_submit_button("Envoyer le lien de réinitialisation", width="stretch")
            if submitted:
                if not email:
                    st.error("❌ Merci de saisir ton email.")
                else:
                    ok, msg = auth_firebase.send_password_reset(email)
                    (st.success if ok else st.error)(f"{'✅' if ok else '❌'} {msg}")


def render_profile():
    profile = st.session_state.user_profile
    auth = st.session_state.auth_user

    col_avatar, col_info, col_logout = st.columns([1, 4, 1])
    with col_avatar:
        st.markdown(
            f'<div style="display:flex;justify-content:center;">{community_db.avatar_html(profile, size=64)}</div>',
            unsafe_allow_html=True,
        )
    with col_info:
        st.markdown(f"### {profile['pseudo']}")
        contact = profile.get("email") or profile.get("phone") or ""
        st.caption(f"{contact} · membre depuis le {profile['created_at'][:10]}")
    with col_logout:
        if st.button("🚪 Déconnexion", width="stretch"):
            _do_logout()

    st.markdown("---")

    updated = community_db.refresh_followed_picks_results(profile["id"])
    if updated:
        st.toast(f"🔄 {updated} pronostic(s) suivi(s) mis à jour avec le résultat réel.")

    stats = community_db.get_user_stats(profile["id"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("💬 Messages postés", stats["messages_count"])
    c2.metric("🎯 Pronostics suivis", stats["followed_count"])
    c3.metric("✅ Vérifiés", stats["checked_count"])
    success_display = f"{stats['success_rate']:.0f}%" if stats["success_rate"] is not None else "—"
    c4.metric("📊 Taux de réussite", success_display)

    st.markdown("---")

    with st.expander("✏️ Modifier mon profil"):
        with st.form("edit_profile_form"):
            new_pseudo = st.text_input("Pseudo", value=profile["pseudo"])
            col_a, col_b = st.columns(2)
            with col_a:
                new_avatar = st.selectbox(
                    "Avatar (emoji)", AVATAR_CHOICES,
                    index=AVATAR_CHOICES.index(profile["avatar_emoji"]) if profile["avatar_emoji"] in AVATAR_CHOICES else 0,
                )
            with col_b:
                new_photo = st.file_uploader("Nouvelle photo (remplace l'emoji)", type=["png", "jpg", "jpeg"])
            remove_photo = st.checkbox("Supprimer ma photo (revenir à l'emoji)") if profile.get("avatar_image_b64") else False

            if st.form_submit_button("Enregistrer"):
                if new_pseudo != profile["pseudo"] and community_db.pseudo_taken(new_pseudo):
                    st.error("❌ Ce pseudo est déjà pris.")
                else:
                    avatar_b64 = _process_avatar_upload(new_photo) if new_photo else None
                    community_db.update_profile(
                        profile["id"], pseudo=new_pseudo, avatar_emoji=new_avatar,
                        avatar_image_b64=avatar_b64, clear_avatar_image=remove_photo,
                    )
                    st.session_state.user_profile = community_db.get_user_by_id(profile["id"])
                    st.success("✅ Profil mis à jour.")
                    st.rerun()

    st.markdown("### 🎯 Mes pronostics suivis")
    picks = community_db.list_followed_picks(profile["id"])
    if not picks:
        st.info("Tu n'as encore suivi aucun pronostic. Va sur la page **Pronostics** et clique « Suivre ce pronostic ».")
    else:
        for p in picks:
            if p["result_checked"]:
                badge = "✅ Gagné" if p["was_correct"] else "❌ Perdu"
            else:
                badge = "⏳ En attente"
            st.markdown(
                f"**{p['home']} vs {p['away']}** — pronostic `{p['prediction']}` "
                f"(confiance {p['confidence']:.0%}, cote {p['cote']:.2f}) — {badge}"
            )


def render():
    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None
    if "user_profile" not in st.session_state:
        st.session_state.user_profile = None

    if _is_logged_in():
        render_profile()
    else:
        render_login_signup()
