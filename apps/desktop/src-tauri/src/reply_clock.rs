use std::time::{Duration, Instant};

/// Bridge allowance includes prompt preparation and optional two-pass review.
/// Only visible answer text extends the idle window; the whole request stays bounded.
pub struct ReplyClock {
    started: Instant,
    first_wait: Duration,
    last_text: Option<Instant>,
}

impl ReplyClock {
    pub fn new(now: Instant, careful: bool) -> Self {
        Self {
            started: now,
            first_wait: Duration::from_secs(if careful { 900 } else { 600 }),
            last_text: None,
        }
    }

    pub fn text_received(&mut self, now: Instant) {
        self.last_text = Some(now);
    }

    pub fn remaining(&self, now: Instant) -> Duration {
        let phase = match self.last_text {
            Some(last) => Duration::from_secs(180).saturating_sub(now.duration_since(last)),
            None => self
                .first_wait
                .saturating_sub(now.duration_since(self.started)),
        };
        phase.min(Duration::from_secs(1800).saturating_sub(now.duration_since(self.started)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cold_start_and_active_reply_can_exceed_the_old_total_deadline() {
        let start = Instant::now();
        let mut clock = ReplyClock::new(start, false);
        assert!(!clock.remaining(start + Duration::from_secs(301)).is_zero());
        clock.text_received(start + Duration::from_secs(450));
        clock.text_received(start + Duration::from_secs(620));
        assert_eq!(
            clock.remaining(start + Duration::from_secs(700)).as_secs(),
            100
        );
    }

    #[test]
    fn silence_and_stalled_replies_expire() {
        let start = Instant::now();
        let mut clock = ReplyClock::new(start, false);
        assert!(clock.remaining(start + Duration::from_secs(600)).is_zero());
        clock.text_received(start + Duration::from_secs(20));
        assert!(clock.remaining(start + Duration::from_secs(200)).is_zero());
    }

    #[test]
    fn continuous_progress_cannot_remove_the_total_bound() {
        let start = Instant::now();
        let mut clock = ReplyClock::new(start, true);
        clock.text_received(start + Duration::from_secs(1799));
        assert!(clock.remaining(start + Duration::from_secs(1800)).is_zero());
    }
}
