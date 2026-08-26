"""Tests von Rate-Limiting und Wiederholversuchen."""

from __future__ import annotations

import pytest

from aktienmonitor.providers.throttle import (
    AccessForbidden,
    RateLimitExceeded,
    ThrottleRegistry,
    TokenBucket,
    call_with_retry,
)


class TestTokenBucket:
    def test_startet_gefuellt(self):
        bucket = TokenBucket(60)
        for _ in range(60):
            assert bucket.try_acquire()
        # Der 61. Zugriff innerhalb derselben Minute wird abgelehnt.
        assert not bucket.try_acquire()

    def test_ungueltige_rate_wird_abgelehnt(self):
        with pytest.raises(ValueError):
            TokenBucket(0)

    def test_acquire_wartet_nicht_wenn_tokens_da_sind(self):
        assert TokenBucket(60).acquire() == 0.0

    def test_unbekannte_quelle_wird_nicht_gedrosselt(self):
        assert ThrottleRegistry({"finnhub": 60}).acquire("unbekannt") == 0.0


class TestCallWithRetry:
    def test_erfolg_im_ersten_versuch(self):
        assert call_with_retry(lambda: 42, sleep=lambda _: None) == 42

    def test_wiederholt_bei_rate_limit(self):
        versuche = []

        def flaky():
            versuche.append(1)
            if len(versuche) < 3:
                raise RateLimitExceeded("429")
            return "ok"

        assert call_with_retry(flaky, max_attempts=4, sleep=lambda _: None) == "ok"
        assert len(versuche) == 3

    def test_gibt_nach_max_versuchen_auf(self):
        versuche = []

        def immer_fehler():
            versuche.append(1)
            raise RateLimitExceeded("429")

        with pytest.raises(RateLimitExceeded):
            call_with_retry(immer_fehler, max_attempts=3, sleep=lambda _: None)
        assert len(versuche) == 3

    def test_gesperrter_endpunkt_wird_nicht_wiederholt(self):
        versuche = []

        def gesperrt():
            versuche.append(1)
            raise AccessForbidden("403")

        with pytest.raises(AccessForbidden):
            call_with_retry(gesperrt, max_attempts=4, sleep=lambda _: None)
        # Warten macht einen gesperrten Endpunkt nicht frei - genau ein Versuch.
        assert len(versuche) == 1

    def test_wartezeiten_wachsen_exponentiell(self):
        wartezeiten = []

        def immer_fehler():
            raise RateLimitExceeded("429")

        with pytest.raises(RateLimitExceeded):
            call_with_retry(
                immer_fehler, max_attempts=4, base_delay=1.0, sleep=wartezeiten.append
            )
        assert len(wartezeiten) == 3
        # 1s, 2s, 4s - jeweils mit bis zu 25 % zufaelligem Aufschlag.
        assert 1.0 <= wartezeiten[0] < 1.25
        assert 2.0 <= wartezeiten[1] < 2.5
        assert 4.0 <= wartezeiten[2] < 5.0

    def test_unerwartete_fehler_werden_nicht_wiederholt(self):
        versuche = []

        def kaputt():
            versuche.append(1)
            raise ValueError("Programmfehler")

        with pytest.raises(ValueError):
            call_with_retry(kaputt, max_attempts=4, sleep=lambda _: None)
        assert len(versuche) == 1
