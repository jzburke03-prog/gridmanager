"""Music and sound effects, built on pygame.mixer. No new dependencies.

Everything here is best-effort by design. A machine with no audio device, a
missing assets/audio folder, or an unreadable file must never stop the grid from
running -- each failure is reported once, concisely, and then the manager quietly
becomes a no-op. Nothing is silently swallowed: every degradation prints exactly
one line saying what is missing and what the consequence is.

Expected layout (relative to this file, so it is cross-platform):

    energy_grid_game/assets/audio/
        music/gameplay_loop.ogg
        sfx/ui_click.wav
        sfx/dialogue_advance.wav
        sfx/correct.wav
        sfx/invalid.wav
        sfx/day_complete.wav
        sfx/next_day.wav
        sfx/success.wav
        sfx/failure.wav
        sfx/emergency.wav

None of these ship with the repo yet; the hooks are wired and the game runs
silently until the files are dropped in.
"""
from pathlib import Path

import pygame

AUDIO_DIR = Path(__file__).resolve().parent / "assets" / "audio"
MUSIC_DIR = AUDIO_DIR / "music"
SFX_DIR = AUDIO_DIR / "sfx"

DEFAULT_MUSIC_VOLUME = 0.35
DEFAULT_SFX_VOLUME = 0.65

# name -> filename. Music is streamed; sfx are loaded into memory.
MUSIC_TRACKS = {
    "gameplay": "gameplay_loop.ogg",
}

SFX_FILES = {
    "ui_click": "ui_click.wav",
    "dialogue_advance": "dialogue_advance.wav",
    "correct": "correct.wav",
    "invalid": "invalid.wav",
    "day_complete": "day_complete.wav",
    "next_day": "next_day.wav",
    "success": "success.wav",
    "failure": "failure.wav",
    "emergency": "emergency.wav",
}

# Don't let a rapidly-retriggering hook stack copies of one sound on top of
# itself; a second play within this window is dropped.
RETRIGGER_GUARD_MS = 60


class AudioManager:
    def __init__(self, music_volume=DEFAULT_MUSIC_VOLUME, sfx_volume=DEFAULT_SFX_VOLUME):
        self.available = False
        self.muted = False
        self.music_volume = music_volume
        self.sfx_volume = sfx_volume
        self._sounds = {}
        self._last_played = {}
        self._current_track = None
        self._failed_tracks = set()
        self._missing_reported = set()

        try:
            pygame.mixer.init()
            self.available = True
        except pygame.error as exc:
            # No device, no ALSA, headless CI -- all normal. Say so once and move on.
            print(f"[audio] disabled: mixer init failed ({exc}). Running without sound.")
            return

        if not AUDIO_DIR.is_dir():
            print(f"[audio] no audio assets at {AUDIO_DIR} - running silently. "
                  f"Expected: music/{MUSIC_TRACKS['gameplay']}, "
                  f"sfx/{{{', '.join(sorted(SFX_FILES.values()))}}}")
            return

        self._load_sounds()

    # -- loading ----------------------------------------------------------

    def _load_sounds(self):
        for name, filename in SFX_FILES.items():
            path = SFX_DIR / filename
            if not path.is_file():
                continue
            try:
                sound = pygame.mixer.Sound(str(path))
                sound.set_volume(self.sfx_volume)
                self._sounds[name] = sound
            except pygame.error as exc:
                print(f"[audio] could not load {path.name}: {exc}")
        missing = sorted(set(SFX_FILES) - set(self._sounds))
        if missing:
            print(f"[audio] {len(self._sounds)}/{len(SFX_FILES)} sfx loaded; "
                  f"missing: {', '.join(missing)}")

    # -- music ------------------------------------------------------------

    def play_music(self, track="gameplay", loop=True, fade_ms=600):
        """Idempotent, and safe to call every frame: asking for the track that is
        already selected returns immediately.

        The guard is on the requested track alone, deliberately not on
        mixer.music.get_busy(). get_busy() is False on drivers that don't report
        playback and after a non-looping track ends, so gating on it would make
        this reload and restart the music on every single frame.
        """
        if not self.available:
            return
        if self._current_track == track or track in self._failed_tracks:
            return
        filename = MUSIC_TRACKS.get(track)
        if filename is None:
            return
        path = MUSIC_DIR / filename
        if not path.is_file():
            self._report_missing(path)
            self._failed_tracks.add(track)   # don't stat it again every frame
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume)
            pygame.mixer.music.play(-1 if loop else 0, fade_ms=fade_ms)
            self._current_track = track
        except pygame.error as exc:
            # Retrying a track that cannot be decoded would re-log and re-load on
            # every frame forever; give up on it once and say so once.
            print(f"[audio] could not play {path.name}: {exc}. That track is disabled.")
            self._failed_tracks.add(track)
            self._current_track = None

    def stop_music(self, fade_ms=400):
        if not self.available:
            return
        pygame.mixer.music.fadeout(fade_ms) if fade_ms else pygame.mixer.music.stop()
        self._current_track = None

    def pause_music(self):
        if self.available and self._current_track:
            pygame.mixer.music.pause()

    def resume_music(self):
        if self.available and self._current_track:
            pygame.mixer.music.unpause()

    def duck_music(self, factor=0.4):
        """Drop music under an outcome screen without tearing it down, so a retry
        can bring it straight back."""
        if self.available and self._current_track:
            pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume * factor)

    def unduck_music(self):
        if self.available and self._current_track:
            pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume)

    # -- sfx --------------------------------------------------------------

    def play(self, name):
        if not self.available or self.muted:
            return
        sound = self._sounds.get(name)
        if sound is None:
            self._report_missing(SFX_DIR / SFX_FILES.get(name, f"{name}.wav"))
            return
        now = pygame.time.get_ticks()
        if now - self._last_played.get(name, -RETRIGGER_GUARD_MS) < RETRIGGER_GUARD_MS:
            return
        self._last_played[name] = now
        try:
            sound.play()
        except pygame.error as exc:
            print(f"[audio] could not play {name}: {exc}")

    play_sound = play  # alias

    # -- volume / mute ----------------------------------------------------

    def set_music_volume(self, volume):
        self.music_volume = max(0.0, min(1.0, volume))
        if self.available and not self.muted:
            pygame.mixer.music.set_volume(self.music_volume)

    def set_sfx_volume(self, volume):
        self.sfx_volume = max(0.0, min(1.0, volume))
        for sound in self._sounds.values():
            sound.set_volume(0.0 if self.muted else self.sfx_volume)

    def toggle_mute(self):
        self.muted = not self.muted
        if not self.available:
            return self.muted
        pygame.mixer.music.set_volume(0.0 if self.muted else self.music_volume)
        for sound in self._sounds.values():
            sound.set_volume(0.0 if self.muted else self.sfx_volume)
        return self.muted

    # -- helpers ----------------------------------------------------------

    def _report_missing(self, path: Path):
        key = str(path)
        if key in self._missing_reported:
            return
        self._missing_reported.add(key)
        print(f"[audio] missing file: {path} (that cue will stay silent)")
