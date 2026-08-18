# -*- coding: utf-8 -*-
"""
max_avatar.py — Avatar animé de Max (le chatbot), pour un rendu "pro".
==============================================================================
Reprend exactement le langage visuel déjà utilisé ailleurs dans l'app
(navy #0a0e1a, cyan #33c7ff, or #f5c451, vert #2ecc87 — voir le bloc CSS
global dans common.py) plutôt que d'inventer une nouvelle palette : un orb
lumineux façon "projecteur de stade / scoreboard", avec un anneau conique et
un mini égaliseur audio.

Trois états, contrôlés depuis Python (le mode determine quel CSS/anim jouer) :
  - "idle"     : respiration douce, prêt à discuter (point vert).
  - "thinking" : anneau qui tourne vite + barres qui s'agitent (point ambre) —
                 affiché pendant que Max traite la demande (texte ou vocal).
  - "speaking" : un <audio> caché est intégré et lu automatiquement ; du JS,
                 DANS LE MÊME composant (donc DOM accessible), écoute les
                 événements play/pause/ended de cet audio pour activer/désactiver
                 l'animation de l'égaliseur EN TEMPS RÉEL, synchronisée à la
                 voix réellement en train de jouer — pas une simple boucle
                 minutée. Une fois l'audio terminé, l'avatar revient à "idle".

Utilisation :
    from max_avatar import render_avatar
    avatar_slot = st.empty()
    render_avatar(avatar_slot, "idle")
    ...
    render_avatar(avatar_slot, "thinking")
    reply = generate(...)
    render_avatar(avatar_slot, "speaking", audio_bytes=mp3_bytes)
"""

import base64

import streamlit.components.v1 as components

_STYLE = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@600;700&family=Inter:wght@400;600&display=swap');
  html, body { margin:0; background:transparent; font-family:'Inter',sans-serif; }
  .stage {
    display:flex; align-items:center; gap:18px;
    background:linear-gradient(135deg,#0d1424,#111a30);
    border:1px solid rgba(255,255,255,0.08);
    border-radius:16px; padding:16px 20px;
  }
  .orb-wrap { position:relative; width:88px; height:88px; flex:0 0 auto; }
  .ring {
    position:absolute; inset:-6px; border-radius:50%;
    background:conic-gradient(from 0deg,#33c7ff,#f5c451,#2ecc87,#33c7ff);
    opacity:.5; animation: spin 6s linear infinite;
  }
  .orb {
    position:absolute; inset:0; border-radius:50%;
    background:radial-gradient(circle at 35% 30%,#1c2b4a,#0a0e1a 70%);
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 0 0 3px #0a0e1a inset, 0 0 22px rgba(51,199,255,.35);
    animation: breathe 3.6s ease-in-out infinite;
  }
  .bars { display:flex; align-items:flex-end; gap:4px; height:30px; }
  .bars span {
    width:5px; border-radius:3px; height:7px;
    background:linear-gradient(180deg,#33c7ff,#f5c451);
    animation: idlebar 2.4s ease-in-out infinite;
  }
  .bars span:nth-child(1){animation-delay:0s;}
  .bars span:nth-child(2){animation-delay:.15s;}
  .bars span:nth-child(3){animation-delay:.3s;}
  .bars span:nth-child(4){animation-delay:.45s;}
  .bars span:nth-child(5){animation-delay:.6s;}
  @keyframes breathe { 0%,100%{transform:scale(1);} 50%{transform:scale(1.04);} }
  @keyframes spin { to { transform:rotate(360deg); } }
  @keyframes idlebar { 0%,100%{height:6px;} 50%{height:14px;} }

  .stage.thinking .ring { animation-duration:1.1s; opacity:.9; }
  .stage.thinking .bars span { animation-name:thinkbar; animation-duration:.85s; }
  @keyframes thinkbar { 0%,100%{height:6px;} 50%{height:22px;} }

  .orb-wrap.is-speaking .ring { animation-duration:1.5s; opacity:1; }
  .orb-wrap.is-speaking .orb { box-shadow:0 0 0 3px #0a0e1a inset, 0 0 30px rgba(51,199,255,.6); }
  .orb-wrap.is-speaking .bars span { animation-name:speakbar; animation-duration:.45s; }
  @keyframes speakbar { 0%,100%{height:6px;} 50%{height:28px;} }

  .identity { display:flex; flex-direction:column; }
  .name { font-family:'Space Grotesk',sans-serif; font-weight:700; font-size:21px; letter-spacing:.05em; color:#e8ecff; }
  .role { font-size:12px; color:#8792ab; margin-top:1px; }
  .statusline { font-size:11.5px; color:#8792ab; margin-top:6px; display:flex; align-items:center; }
  .dot { width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:6px; }
  .dot.idle { background:#2ecc87; box-shadow:0 0 6px #2ecc87; }
  .dot.thinking { background:#f5c451; box-shadow:0 0 6px #f5c451; animation:blink 1s steps(2) infinite; }
  .dot.speaking { background:#33c7ff; box-shadow:0 0 6px #33c7ff; }
  @keyframes blink { 50%{opacity:.25;} }
</style>
"""

_STATUS = {
    "idle": ("idle", "Prêt à discuter"),
    "thinking": ("thinking", "Max réfléchit..."),
    "speaking": ("speaking", "Max te répond à voix haute"),
}


def _html(mode: str, audio_b64: str | None = None) -> str:
    stage_class = "thinking" if mode == "thinking" else ""
    dot_class, status_text = _STATUS.get(mode, _STATUS["idle"])

    audio_block = ""
    js_block = ""
    if mode == "speaking" and audio_b64:
        audio_block = (
            f'<audio id="ttsAudio" autoplay style="display:none">'
            f'<source src="data:audio/mp3;base64,{audio_b64}" type="audio/mpeg"></audio>'
        )
        js_block = """
        const audio = document.getElementById('ttsAudio');
        const wrap = document.getElementById('orbWrap');
        const statusEl = document.getElementById('statusText');
        const dotEl = document.getElementById('statusDot');
        function toIdle() {
          wrap.classList.remove('is-speaking');
          statusEl.textContent = 'Pret a discuter';
          dotEl.className = 'dot idle';
        }
        audio.addEventListener('play', () => {
          wrap.classList.add('is-speaking');
          statusEl.textContent = 'Max te repond a voix haute';
          dotEl.className = 'dot speaking';
        });
        audio.addEventListener('pause', toIdle);
        audio.addEventListener('ended', toIdle);
        """

    return f"""
{_STYLE}
<div class="stage {stage_class}">
  <div class="orb-wrap" id="orbWrap">
    <div class="ring"></div>
    <div class="orb"><div class="bars"><span></span><span></span><span></span><span></span><span></span></div></div>
  </div>
  <div class="identity">
    <div class="name">MAX</div>
    <div class="role">Copilote pronostics IA</div>
    <div class="statusline"><span class="dot {dot_class}" id="statusDot"></span><span id="statusText">{status_text}</span></div>
  </div>
</div>
{audio_block}
<script>{js_block}</script>
"""


def render_avatar(slot, mode: str = "idle", audio_bytes: bytes | None = None):
    """Affiche/actualise l'avatar de Max dans le placeholder `slot` (st.empty()).
    mode: "idle" | "thinking" | "speaking". audio_bytes: mp3 à lire en mode "speaking"."""
    audio_b64 = base64.b64encode(audio_bytes).decode("ascii") if audio_bytes else None
    with slot.container():
        components.html(_html(mode, audio_b64), height=130)
