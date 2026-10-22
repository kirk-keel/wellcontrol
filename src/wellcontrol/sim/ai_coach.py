"""AI-Powered Assessment & Intelligent Coaching Engine.

Provides automated IADC / IWCF Level 3/4 supervisor-standard assessment,
qualitative evaluation of student decision-making narrative, technique analysis
(choke smoothness, lag time awareness, gas expansion anticipation), point
deductions, and actionable timestamped instructor coaching feedback.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .assessment import EventKind, Grade, Severity, assess

if TYPE_CHECKING:
    from .session import Session


@dataclass
class CompetencyCategory:
    name: str
    score: float
    max_score: float
    weight_pct: int
    feedback: str

    @property
    def percentage(self) -> int:
        return int(round((self.score / max(self.max_score, 1e-6)) * 100))


@dataclass
class Deduction:
    penalty: float
    category: str
    reason: str
    timestamp: str | None = None


@dataclass
class CoachingInsight:
    time_str: str
    stage: str
    observation: str
    recommendation: str
    severity: str = "info"


@dataclass
class AICoachReport:
    score: int
    letter_grade: str
    iwcf_standard: str
    verdict: str
    executive_summary: str
    categories: list[CompetencyCategory]
    strengths: list[str]
    deductions: list[Deduction]
    coaching_timeline: list[CoachingInsight]
    recommended_exercises: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "letter_grade": self.letter_grade,
            "iwcf_standard": self.iwcf_standard,
            "verdict": self.verdict,
            "executive_summary": self.executive_summary,
            "categories": [
                {
                    "name": c.name,
                    "score": round(c.score, 1),
                    "max_score": c.max_score,
                    "percentage": c.percentage,
                    "weight_pct": c.weight_pct,
                    "feedback": c.feedback,
                }
                for c in self.categories
            ],
            "strengths": self.strengths,
            "deductions": [
                {
                    "penalty": round(d.penalty, 1),
                    "category": d.category,
                    "reason": d.reason,
                    "timestamp": d.timestamp,
                }
                for d in self.deductions
            ],
            "coaching_timeline": [
                {
                    "time": ci.time_str,
                    "stage": ci.stage,
                    "observation": ci.observation,
                    "recommendation": ci.recommendation,
                    "severity": ci.severity,
                }
                for ci in self.coaching_timeline
            ],
            "recommended_exercises": self.recommended_exercises,
        }


def evaluate_student_session(session: "Session") -> AICoachReport:
    """Analyze a student session and produce a comprehensive AI coaching evaluation."""
    sim = session.simulator
    state = sim.state
    standard_assessment = assess(sim, session.scenario.standard if session.scenario else None)
    events = state.event_log.events
    samples = state.trace

    deductions: list[Deduction] = []
    strengths: list[str] = []
    timeline: list[CoachingInsight] = []

    # Category base scores
    cat1_score = 25.0  # Kick Detection, Shut-In & Space-Out (25 pts)
    cat2_score = 35.0  # Pressure Control & Choke Modulation (35 pts)
    cat3_score = 20.0  # Casing Shoe & Wellbore Integrity (20 pts)
    cat4_score = 20.0  # Procedure & Kill Execution (20 pts)

    # -------------------------------------------------------------------------
    # 1. Kick Detection & Shut-In Evaluation (Category 1)
    # -------------------------------------------------------------------------
    cat1_feedback = []
    if sim.start.value == "drilling":
        kick_event = next((e for e in events if e.kind == EventKind.KICK_ZONE_DRILLED), None)
        shut_event = next((e for e in events if e.kind == EventKind.WELL_SHUT_IN_BY_STUDENT), None)

        if shut_event:
            gain = state.pit_gain_bbl
            if gain <= 12.0:
                strengths.append(f"Prompt kick detection: Shut in at {gain:.1f} bbl pit gain, minimizing kick intensity.")
                cat1_feedback.append(f"Excellent kick recognition! Space-out and shut-in executed promptly with only {gain:.1f} bbl influx.")
            elif gain <= 20.0:
                penalty = min(6.0, (gain - 12.0) * 0.75)
                deductions.append(Deduction(penalty, "Kick Detection", f"Delayed kick recognition: Pit gain reached {gain:.1f} bbl before shut-in.", shut_event.clock))
                cat1_score -= penalty
                cat1_feedback.append(f"Satisfactory shut-in at {gain:.1f} bbl gain. Aim to identify flow line increases earlier.")
            else:
                penalty = min(15.0, (gain - 12.0) * 0.9)
                deductions.append(Deduction(penalty, "Kick Detection", f"Excessive influx taken ({gain:.1f} bbl) before shut-in.", shut_event.clock))
                cat1_score -= penalty
                cat1_feedback.append(f"Sluggish kick detection: Allowed {gain:.1f} bbl into wellbore. Monitor active pit levels continuously.")
        else:
            penalty = 25.0
            deductions.append(Deduction(penalty, "Kick Detection", "Failed to shut in well after drilling into kick zone.", None))
            cat1_score = 0.0
            cat1_feedback.append("Critical failure: The well was never shut in by the student.")
    else:
        # Pre-shut in start
        cat1_feedback.append("Initial shut-in conditions accepted and verified correctly from start of exercise.")
        strengths.append("Verified shut-in casing and drill pipe pressures prior to commencing kill operations.")

    # -------------------------------------------------------------------------
    # 2. Pressure Control & Choke Modulation Evaluation (Category 2)
    # -------------------------------------------------------------------------
    cat2_feedback = []
    elapsed_s = max(state.time_s, 1.0)
    outside_pct = (state.seconds_outside_band / elapsed_s) * 100.0

    if outside_pct < 2.0:
        strengths.append("Exceptional bottomhole pressure stability: Maintained within target band for >98% of the operation.")
        cat2_feedback.append("Flawless bottomhole pressure control with smooth, measured choke adjustments.")
    elif outside_pct < 10.0:
        penalty = outside_pct * 0.8
        deductions.append(Deduction(penalty, "Choke Modulation", f"BHP departed target band for {outside_pct:.1f}% of simulation duration."))
        cat2_score -= penalty
        cat2_feedback.append("Acceptable pressure tracking with minor hunting during pump rate transitions.")
    else:
        penalty = min(25.0, outside_pct * 1.0)
        deductions.append(Deduction(penalty, "Choke Modulation", f"Excessive pressure excursions: {outside_pct:.1f}% of run outside safe BHP band."))
        cat2_score -= penalty
        cat2_feedback.append(f"Erratic choke control: Bottomhole pressure drifted outside allowable band for {outside_pct:.1f}% of time.")

    # Max BHP excursion check
    max_excursion = state.max_bhp_excursion_psi
    if max_excursion > 150.0:
        penalty = min(10.0, (max_excursion - 150.0) / 25.0)
        deductions.append(Deduction(penalty, "Pressure Excursion", f"Peak bottomhole pressure excursion of {max_excursion:.0f} psi."))
        cat2_score -= penalty
        timeline.append(CoachingInsight("Phase Peak", "Circulation", f"BHP swung {max_excursion:.0f} psi from formation pore pressure.", "Allow ~2 seconds per 1,000 ft of depth for pressure pulses to arrive before readjusting choke.", "warning"))

    # Influx taken while circulating (underbalance)
    if state.influx_taken_bbl > 0.5:
        penalty = min(12.0, state.influx_taken_bbl * 4.0)
        deductions.append(Deduction(penalty, "Underbalance", f"Allowed secondary kick of {state.influx_taken_bbl:.1f} bbl into wellbore during circulation."))
        cat2_score -= penalty
        timeline.append(CoachingInsight("Circulation", "Underbalance", f"Secondary influx of {state.influx_taken_bbl:.1f} bbl admitted.", "Never allow drill pipe pressure to drop below schedule while circulating kill mud.", "critical"))

    # -------------------------------------------------------------------------
    # 3. Casing Shoe & Wellbore Integrity Evaluation (Category 3)
    # -------------------------------------------------------------------------
    cat3_feedback = []
    if sim.frac_pressure_psi is not None:
        shoe_margin = sim.frac_pressure_psi - state.peak_shoe_pressure_psi
        if shoe_margin < 0:
            penalty = 20.0
            deductions.append(Deduction(penalty, "Shoe Breakdown", f"CRITICAL: Exceeded formation fracture pressure by {abs(shoe_margin):.0f} psi! Underground blowout triggered.", None))
            cat3_score = 0.0
            cat3_feedback.append("CRITICAL FAILURE: Formation fractured at casing shoe due to excessive backpressure.")
            timeline.append(CoachingInsight("Shoe Peak", "Integrity Breach", f"Peak shoe pressure reached {state.peak_shoe_pressure_psi:.0f} psi (Frac limit {sim.frac_pressure_psi:.0f} psi).", "Anticipate gas expansion when bubble approaches casing shoe; ease choke open to avoid fracturing seat.", "critical"))
        elif shoe_margin < 150.0:
            penalty = min(8.0, (150.0 - shoe_margin) * 0.08)
            deductions.append(Deduction(penalty, "Shoe Margin", f"Casing seat margin narrowed dangerously to {shoe_margin:.0f} psi."))
            cat3_score -= penalty
            cat3_feedback.append(f"Maintained casing seat integrity, but margin dropped to a narrow {shoe_margin:.0f} psi.")
        else:
            strengths.append(f"Preserved safe formation integrity with a healthy {shoe_margin:.0f} psi safety margin at the shoe.")
            cat3_feedback.append(f"Excellent casing shoe management with {shoe_margin:.0f} psi margin preserved.")

    if state.lost_bbl > 0.5:
        penalty = min(10.0, state.lost_bbl * 3.0)
        deductions.append(Deduction(penalty, "Formation Losses", f"Lost {state.lost_bbl:.1f} bbl of drilling fluid to the formation."))
        cat3_score -= penalty

    # -------------------------------------------------------------------------
    # 4. Procedure & Kill Execution Evaluation (Category 4)
    # -------------------------------------------------------------------------
    cat4_feedback = []
    scenario_key = session.scenario.key if session.scenario else "custom"

    if state.well_is_dead:
        strengths.append("Successfully executed procedure to achieve a fully dead, hydrostatic-controlled well.")
        cat4_feedback.append("Complete procedure success: Zero surface pressure with formation safely balanced.")
    elif standard_assessment.standard.require_kill:
        penalty = 12.0
        deductions.append(Deduction(penalty, "Kill Completion", "Exercise terminated before well was fully dead.", None))
        cat4_score -= penalty
        cat4_feedback.append("Kill incomplete: Well was not fully displaced to kill mud at shut-down.")
    else:
        cat4_feedback.append("Exercise completed according to designated stage objectives.")

    # Equipment Malfunction handling
    fault_events = [e for e in events if e.kind == EventKind.EQUIPMENT_FAILURE]
    if fault_events:
        for fe in fault_events:
            timeline.append(CoachingInsight(fe.clock, "Fault Response", f"Equipment anomaly: {fe.message}", "Check standby equipment or line up alternate choke manifold paths immediately.", "warning"))
        strengths.append("Demonstrated operational poise when confronted with unexpected equipment failure.")

    # Method specific checks
    if scenario_key == "drillers":
        if state.pumped_bbl > 100:
            timeline.append(CoachingInsight("Circulation 1", "Driller's Method", "Influx displaced using original mud weight.", "Verify shut-in pressures equalize (SIDPP == SICP) before starting circulation 2 with KMW.", "info"))
    elif scenario_key == "wait_and_weight":
        timeline.append(CoachingInsight("Circulation", "Wait and Weight", "Displaced string with KMW following step-down schedule.", "Ensure smooth transition from ICP to FCP as kill mud reaches bit nozzles.", "info"))
    elif scenario_key == "bullhead":
        if state.injected_bbl > 5.0:
            strengths.append(f"Successfully bullheaded {state.injected_bbl:.1f} bbl into formation without rupturing casing shoe.")

    # Clamp category scores
    cat1_score = max(0.0, min(25.0, cat1_score))
    cat2_score = max(0.0, min(35.0, cat2_score))
    cat3_score = max(0.0, min(20.0, cat3_score))
    cat4_score = max(0.0, min(20.0, cat4_score))

    total_score = int(round(cat1_score + cat2_score + cat3_score + cat4_score))
    total_score = max(0, min(100, total_score))

    # Automatic Fail overrides
    has_fracture = any(d.category == "Shoe Breakdown" for d in deductions)
    if has_fracture:
        total_score = min(total_score, 45)
        letter = "FAIL"
        iwcf_status = "NOT QUALIFIED — FORMATION INTEGRITY BREACH"
        verdict = "UNSUCCESSFUL (CRITICAL FAILURE)"
    elif total_score >= 90:
        letter = "A+" if total_score >= 95 else "A"
        iwcf_status = "LEVEL 4 SUPERVISOR CERTIFIED (DISTINCTION)"
        verdict = "PASSED WITH EXCELLENCE"
    elif total_score >= 80:
        letter = "B"
        iwcf_status = "LEVEL 4 SUPERVISOR PASS"
        verdict = "PASSED"
    elif total_score >= 70:
        letter = "C"
        iwcf_status = "LEVEL 3 OPERATOR PASS"
        verdict = "MARGINAL PASS"
    elif total_score >= 60:
        letter = "D"
        iwcf_status = "CONDITIONAL (RETEST RECOMMENDED)"
        verdict = "BELOW STANDARD"
    else:
        letter = "FAIL"
        iwcf_status = "NOT QUALIFIED"
        verdict = "FAILED"

    # Executive Summary synthesis
    if total_score >= 85:
        summary = (
            f"Candidate achieved an outstanding score of {total_score}/100 ({letter}). "
            "Displayed disciplined choke handling, keen awareness of downhole pressure transmission lags, "
            "and rigorously protected the casing shoe throughout the exercise."
        )
    elif total_score >= 70:
        summary = (
            f"Candidate achieved a satisfactory score of {total_score}/100 ({letter}). "
            "Demonstrated solid fundamental understanding of constant bottomhole pressure principles, "
            "with opportunities to improve choke modulation smoothness during gas expansion phases."
        )
    else:
        summary = (
            f"Candidate scored {total_score}/100 ({letter}). "
            "Critical deviations from standard well control procedures were observed, including excessive pressure excursions "
            "or compromised wellbore margins. Immediate remediation and supervised practice recommended."
        )

    categories = [
        CompetencyCategory("Kick Detection & Shut-In", cat1_score, 25.0, 25, " ".join(cat1_feedback)),
        CompetencyCategory("Pressure Control & Choke Modulation", cat2_score, 35.0, 35, " ".join(cat2_feedback)),
        CompetencyCategory("Casing Seat & Wellbore Integrity", cat3_score, 20.0, 20, " ".join(cat3_feedback)),
        CompetencyCategory("Procedure & Kill Execution", cat4_score, 20.0, 20, " ".join(cat4_feedback)),
    ]

    # Recommended exercises based on findings
    recommended = []
    if outside_pct > 5.0 or max_excursion > 100.0:
        recommended.append("Driller's Method — Choke modulation drill focusing on lag time pacing.")
    if has_fracture or any(d.category == "Shoe Margin" for d in deductions):
        recommended.append("Weak Casing Seat scenario — Managing pressure margins under strict MAASP limits.")
    if sim.start.value == "drilling" and cat1_score < 20:
        recommended.append("Drilling ahead — Kick detection and rapid hard shut-in drill.")
    if not recommended:
        recommended.append("Wait and Weight scenario with unexpected choke plugged fault injection.")
        recommended.append("Subsea BOP — Choke line friction compensation exercise.")

    return AICoachReport(
        score=total_score,
        letter_grade=letter,
        iwcf_standard=iwcf_status,
        verdict=verdict,
        executive_summary=summary,
        categories=categories,
        strengths=strengths or ["Maintained basic well monitoring throughout the session."],
        deductions=deductions,
        coaching_timeline=timeline,
        recommended_exercises=recommended,
    )
