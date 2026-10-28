"""Per-copy browser profile.

REAL here: a dedicated Chromium profile directory per copy, so each
copy keeps its own logins, cookies and workspace separate (the
OpenBot per-Bot model: one container, one browser profile, one
/workspace per Bot).

UNTESTED everywhere: launching a live Chromium against a profile.
This host has no Chromium binary, and no live browser launch has been
run from this skeleton. launch() therefore refuses instead of faking
a browser session. On a host with Chromium, the launch path still
needs a real test before anyone claims it works.
"""

import json
import shutil
from pathlib import Path

CHROMIUM_BINARIES = ("chromium", "chromium-browser", "google-chrome", "chrome")


def find_chromium():
    for name in CHROMIUM_BINARIES:
        found = shutil.which(name)
        if found:
            return found
    return None


class BrowserProfile:
    def __init__(self, copy_id, base_dir):
        self.copy_id = copy_id
        self.path = Path(base_dir) / "browser-profile"
        self.path.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.path / "PROFILE.json"
        self.chromium = find_chromium()
        self._write_meta(launched=False)

    def _write_meta(self, launched):
        meta = {
            "copy_id": self.copy_id,
            "profile_path": str(self.path),
            "chromium_binary": self.chromium,
            "launched": launched,
            "live_browser": "UNTESTED",
            "note": (
                "Profile dir is real. Live Chromium launch is UNTESTED: "
                "no browser session is created by this skeleton."
            ),
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, sort_keys=True)
        return meta

    def launch(self):
        """Do NOT fake a browser. Raises until a live launch is tested."""
        raise NotImplementedError(
            "UNTESTED: live Chromium launch from this skeleton has never "
            "been run. Refusing instead of faking a browser session."
        )


# ------------------------------------------------- Google-logged-in primary
# The owner signs in to Google HERSELF through the in-chat browser.
# That sign-in persists because the Chromium profile directory keeps
# its cookies/storage — the same mechanism every Chromium profile
# uses. This module NEVER stores her Google password, NEVER automates
# her Google login, and NEVER types credentials. It only reports, by
# reading the profile's cookie database (row counts only, values are
# never read or printed), whether Google session cookies exist.
PRIMARY_PROFILE_NAME = "primary-google"


def primary_profile_dir(base_dir):
    """Directory of the persistent primary (Google-logged-in) profile."""
    return Path(base_dir) / "profiles" / PRIMARY_PROFILE_NAME


class GoogleProfile:
    """The persistent primary profile.

    One profile, shared by Google-dependent work only. Copies each
    keep their OWN profile (BrowserProfile above); Google-dependent
    work explicitly opts into this primary profile. Per-copy Google
    sign-ins would each need the owner's own sign-in and are NOT
    automated — that is a deliberate limit, not a missing feature.
    """

    def __init__(self, base_dir):
        self.path = primary_profile_dir(base_dir)
        self.path.mkdir(parents=True, exist_ok=True)
        self.meta_path = self.path / "GOOGLE_PROFILE.json"
        self._write_meta()

    def _write_meta(self):
        meta = {
            "profile": PRIMARY_PROFILE_NAME,
            "profile_path": str(self.path),
            "google_sign_in": (
                "OWNER SIGNS IN HERSELF through the in-chat browser; "
                "the session persists via Chromium cookies/storage in "
                "this directory. No password is stored anywhere in this "
                "repo, and no automated Google login is performed."
            ),
            "per_copy_google": (
                "NOT AUTOMATED: each copy's own profile would need the "
                "owner's own sign-in before Google-dependent work."
            ),
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, sort_keys=True)
        return meta

    def status(self):
        """REAL check: count Google cookie rows in the profile's
        Chromium Cookies database (read-only, values never read).
        signed_in_likely is True only when Google cookies exist.
        Anything unreadable is reported as unknown, never as signed in.
        """
        cookies_db = self.path / "Cookies"
        result = {
            "profile_path": str(self.path),
            "cookies_db": str(cookies_db),
            "cookies_db_exists": cookies_db.exists(),
            "google_cookie_count": None,
            "signed_in_likely": False,
            "status": "unknown",
        }
        if not cookies_db.exists():
            result["status"] = "no-profile-yet"
            result["note"] = (
                "No Chromium Cookies database in this profile yet — "
                "the owner has not signed in through it, or no browser "
                "has run against it."
            )
            return result
        try:
            import sqlite3

            uri = f"file:{cookies_db}?mode=ro"
            conn = sqlite3.connect(uri, uri=True)
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM cookies "
                    "WHERE host_key LIKE '%google.com%'"
                ).fetchone()
            finally:
                conn.close()
            count = int(row[0]) if row else 0
            result["google_cookie_count"] = count
            result["signed_in_likely"] = count > 0
            result["status"] = (
                "google-cookies-present" if count > 0 else "no-google-cookies"
            )
        except Exception as exc:  # locked DB, missing table, ...
            result["status"] = "unreadable"
            result["note"] = f"Cookies DB could not be read: {type(exc).__name__}"
        return result
