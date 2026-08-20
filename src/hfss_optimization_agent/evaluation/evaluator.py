"""Deterministic, configuration-driven S-parameter performance evaluation."""
from __future__ import annotations
import math
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence
from ..core.models import EvaluationResult, HFSSResult, SParameterResult, FrequencyPlan
from ..interfaces.evaluator import EvaluatorInterface

@dataclass(frozen=True, slots=True)
class SParameterRule:
    rule_id: str
    parameter: str
    frequency_band: tuple[float, float]
    operator: str
    threshold: float
    hard_constraint: bool = True
    frequency_unit: str = "GHz"
    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SParameterRule":
        band = value.get("frequency_band", value.get("band"))
        if isinstance(band, Mapping): band = (band["start"], band["stop"])
        if band is None or len(band) != 2: raise ValueError("frequency_band must contain exactly two values")
        operator = str(value.get("operator", ""))
        if operator not in {"<=", ">="}: raise ValueError("operator must be <= or >=")
        return cls(str(value["rule_id"]), str(value["parameter"]).upper(), (float(band[0]), float(band[1])), operator, float(value["threshold"]), bool(value.get("hard_constraint", True)), str(value.get("frequency_unit", "GHz")))

@dataclass(frozen=True, slots=True)
class SParameterData:
    frequency: list[float]
    S11_dB: list[float]
    S21_dB: list[float]
    frequency_unit: str = "GHz"
    source: str = "unknown"
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class RuleEvaluationResult:
    rule_id: str
    parameter: str
    frequency_band: tuple[float, float]
    target: float
    operator: str
    status: str = "INVALID"
    worst_value: float | None = None
    worst_frequency: float | None = None
    margin_to_target: float | None = None
    violation_ranges: list[dict[str, float]] = field(default_factory=list)
    violation_bandwidth: float = 0.0
    max_violation: float = 0.0
    hard_constraint: bool = True
    def to_dict(self): return asdict(self)

@dataclass(slots=True)
class FrequencyMarginResult:
    achieved_lower_edge: float
    achieved_upper_edge: float
    lower_frequency_margin: float
    upper_frequency_margin: float
    lower_margin_target: float = 1.0
    upper_margin_target: float = 1.0
    lower_margin_remaining: float = 0.0
    upper_margin_remaining: float = 0.0
    def to_dict(self): return asdict(self)

def _factor(unit: str) -> float:
    return {"hz":1e-9,"khz":1e-6,"mhz":1e-3,"ghz":1.0}.get(unit.lower(), 1.0)
def _interp(points, x):
    if x <= points[0][0]: return points[0][1]
    if x >= points[-1][0]: return points[-1][1]
    for (x0,y0),(x1,y1) in zip(points, points[1:]):
        if x0 <= x <= x1: return y0 + (y1-y0)*(x-x0)/(x1-x0)
    return points[-1][1]
def _data(value):
    if isinstance(value, SParameterData): return value
    if isinstance(value, HFSSResult):
        if not value.frequency or not value.s_parameters: return None
        unit = value.execution_metadata.get("frequency_unit") or ("Hz" if max(map(abs,value.frequency),default=0)>1e6 else "GHz")
        return SParameterData(list(value.frequency), list(value.s_parameters.get("s11_db",[])), list(value.s_parameters.get("s21_db",[])), unit, "HFSS")
    if isinstance(value, SParameterResult) and value.response:
        r=value.response
        db=lambda a,b:20*math.log10(max(math.hypot(a,b),1e-300))
        return SParameterData(list(r.frequency_hz),[db(m[0][0],i[0][0]) for m,i in zip(r.real,r.imag)],[db(m[1][0],i[1][0]) for m,i in zip(r.real,r.imag)],"Hz",value.provider)
    if isinstance(value, Mapping): return SParameterData(list(value.get("frequency",[])),list(value.get("S11_dB",value.get("s11_db",[]))),list(value.get("S21_dB",value.get("s21_db",[]))),str(value.get("frequency_unit","GHz")),str(value.get("source","mapping")))
    return None

class DeterministicEvaluator(EvaluatorInterface):
    def __init__(self, *, target_score=0.5, tolerance=1e-12, rules: Sequence[SParameterRule|Mapping[str,Any]]=(), frequency_plan: FrequencyPlan | None = None):
        self.target_score=target_score; self.tolerance=tolerance; self.rules=tuple(r if isinstance(r,SParameterRule) else SParameterRule.from_mapping(r) for r in rules); self.frequency_plan=frequency_plan
    def _invalid(self, cid, stage, reason, plan=None):
        return EvaluationResult(cid,False,False,{}, {}, {},0.0,reason,stage,"INVALID",[],0,0,None,None,{"valid":False,"reason":reason},[],0,0,None,{},plan.to_dict() if plan else {})

    @staticmethod
    def _same_band(actual, expected, tolerance):
        return len(actual) == 2 and all(abs(float(a) - float(e)) <= tolerance for a, e in zip(actual, expected))

    def _validate_rules(self, rules, plan):
        core = tuple(value * _factor("GHz") for value in plan.core_band)
        lower = tuple(value * _factor("GHz") for value in plan.lower_margin_band)
        upper = tuple(value * _factor("GHz") for value in plan.upper_margin_band)
        for rule in rules:
            band = tuple(value * _factor(rule.frequency_unit) for value in rule.frequency_band)
            expected = core if rule.hard_constraint else (lower if self._same_band(band, lower, plan.tolerance_ghz) else upper)
            if not self._same_band(band, expected, plan.tolerance_ghz):
                return False
        return True

    @staticmethod
    def _crossing(x0, m0, x1, m1):
        if m1 == m0:
            return x0
        return x0 + (0.0 - m0) * (x1 - x0) / (m1 - m0)

    def _frequency_margin(self, freq, series, rules, plan):
        lower_rules = [r for r in rules if not r.hard_constraint and r.frequency_band[1] * _factor(r.frequency_unit) >= plan.lower_margin_band[0] and r.frequency_band[0] * _factor(r.frequency_unit) <= plan.lower_margin_band[1]]
        upper_rules = [r for r in rules if not r.hard_constraint and r.frequency_band[1] * _factor(r.frequency_unit) >= plan.upper_margin_band[0] and r.frequency_band[0] * _factor(r.frequency_unit) <= plan.upper_margin_band[1]]
        def side(rule_set, low):
            core, target = (plan.core_band[0], plan.lower_margin_band[0]) if low else (plan.core_band[1], plan.upper_margin_band[1])
            if not rule_set:
                edge = core
                return edge, abs(core - edge)
            points = sorted({target, core, *[x for x in freq if target <= x <= core]}) if low else sorted({core, target, *[x for x in freq if core <= x <= target]})
            bases = {r.rule_id: list(zip(freq, series[r.parameter])) for r in rule_set}
            def margins_at(x):
                return [(r, (r.threshold - _interp(bases[r.rule_id], x) if r.operator == "<=" else _interp(bases[r.rule_id], x) - r.threshold)) for r in rule_set]
            ordered = list(reversed(points)) if low else points
            first = margins_at(ordered[0])
            if any(m < -self.tolerance for _, m in first):
                edge = core
                return edge, abs(core - edge)
            edge = target
            for x0, x1 in zip(ordered, ordered[1:]):
                m0 = margins_at(x0); m1 = margins_at(x1)
                if all(m >= -self.tolerance for _, m in m1):
                    continue
                crossings = [self._crossing(x0, left, x1, right) for (r, left), (_, right) in zip(m0, m1) if left >= -self.tolerance and right < -self.tolerance]
                edge = (max(crossings) if low else min(crossings)) if crossings else x0
                break
            return edge, (core - edge if low else edge - core)
        lower_edge, lower_margin = side(lower_rules, True)
        upper_edge, upper_margin = side(upper_rules, False)
        result = FrequencyMarginResult(lower_edge, upper_edge, lower_margin, upper_margin, plan.lower_margin_target, plan.upper_margin_target, max(0.0, plan.lower_margin_target - lower_margin), max(0.0, plan.upper_margin_target - upper_margin))
        return result.to_dict()
    def evaluate_sparameters(self, value, *, evaluated_stage="optimized", rules=None, candidate_id="unknown", frequency_plan: FrequencyPlan | None = None):
        plan = frequency_plan or self.frequency_plan or FrequencyPlan()
        d=_data(value); active=tuple(self.rules if rules is None else (r if isinstance(r,SParameterRule) else SParameterRule.from_mapping(r) for r in rules))
        if not plan.is_valid:
            return self._invalid(candidate_id,evaluated_stage,plan.validation_error or "Invalid FrequencyPlan.",plan)
        if not active: return self._invalid(candidate_id,evaluated_stage,"No S-parameter evaluation rules configured.",plan)
        if d is None: return self._invalid(candidate_id,evaluated_stage,"S 参数为空",plan)
        if (frequency_plan is not None or self.frequency_plan is not None) and not self._validate_rules(active, plan):
            return self._invalid(candidate_id,evaluated_stage,"S-parameter evaluation rules do not match FrequencyPlan.",plan)
        ff=_factor(d.frequency_unit); raw=[float(x)*ff for x in d.frequency]
        if len(raw)<2 or len(d.S11_dB)!=len(raw) or len(d.S21_dB)!=len(raw): return self._invalid(candidate_id,evaluated_stage,"频率与 S11/S21 数据长度不一致",plan)
        if any(not math.isfinite(x) for x in raw+d.S11_dB+d.S21_dB): return self._invalid(candidate_id,evaluated_stage,"S 参数存在无效值",plan)
        order=sorted(range(len(raw)),key=raw.__getitem__); freq=[raw[i] for i in order]; series={"S11":[d.S11_dB[i] for i in order],"S21":[d.S21_dB[i] for i in order]}; results=[]
        for rule in active:
            lo,hi=sorted((rule.frequency_band[0]*_factor(rule.frequency_unit),rule.frequency_band[1]*_factor(rule.frequency_unit)))
            if freq[0]>lo or freq[-1]<hi: return self._invalid(candidate_id,evaluated_stage,f"频率范围未覆盖规则 {rule.rule_id}",plan)
            values=series.get(rule.parameter); 
            if values is None or len(values)!=len(freq): return self._invalid(candidate_id,evaluated_stage,f"缺失 {rule.parameter} 数据",plan)
            base=list(zip(freq,values)); pts=[(lo,_interp(base,lo)),*((x,y) for x,y in base if lo<=x<=hi),(hi,_interp(base,hi))]; points=sorted(dict(pts).items())
            margins=[(x,rule.threshold-y if rule.operator=="<=" else y-rule.threshold) for x,y in points]; wx,wm=min(margins,key=lambda z:z[1]); wv=dict(points)[wx]; bad=[(x,m) for x,m in margins if m < -self.tolerance]; ranges=[]
            # Split each adjacent interval at the linearly interpolated threshold crossing.
            for (x0,m0),(x1,m1) in zip(margins,margins[1:]):
                if m0 < -self.tolerance and m1 < -self.tolerance:
                    ranges.append({"start":x0,"stop":x1})
                elif (m0 < -self.tolerance) != (m1 < -self.tolerance):
                    if m1 == m0:
                        crossing = x0
                    else:
                        crossing = x0 + (0.0 - m0) * (x1 - x0) / (m1 - m0)
                    if m0 < -self.tolerance:
                        ranges.append({"start":x0,"stop":crossing})
                    else:
                        ranges.append({"start":crossing,"stop":x1})
            merged=[]
            for item in ranges:
                if merged and abs(merged[-1]["stop"] - item["start"]) <= self.tolerance:
                    merged[-1]["stop"] = item["stop"]
                else:
                    merged.append(item)
            ranges = merged
            results.append(RuleEvaluationResult(rule.rule_id,rule.parameter,rule.frequency_band,rule.threshold,rule.operator,"PASS" if wm>=-self.tolerance else "FAIL",wv,wx,wm,ranges,sum(r["stop"]-r["start"] for r in ranges),max((max(0,-m) for _,m in bad),default=0),rule.hard_constraint))
        hard=[r for r in results if r.hard_constraint]; soft=[r for r in results if not r.hard_constraint]; failed_hard=[r for r in hard if r.status=="FAIL"]; failed_soft=[r for r in soft if r.status=="FAIL"]
        status="PASS" if all(r.status=="PASS" for r in hard) else "FAIL"; worst=min(failed_hard,key=lambda r:r.margin_to_target or 0,default=None); worst_soft=min(failed_soft,key=lambda r:r.margin_to_target or 0,default=None)
        frequency_margin=self._frequency_margin(freq,series,active,plan)
        return EvaluationResult(candidate_id,False,status=="PASS",{}, {}, {},0.0,f"{status}: {len(results)} rules",evaluated_stage,status,[r.to_dict() for r in results],sum(r.status=="PASS" for r in results),sum(r.status=="FAIL" for r in results),worst.to_dict() if worst else None,worst.margin_to_target if worst else None,{"source":d.source,"frequency_unit":"GHz","points":len(freq)},[asdict(r) for r in active],len(failed_hard),len(failed_soft),worst_soft.to_dict() if worst_soft else None,frequency_margin,plan.to_dict())
    def evaluate(self, *, candidate_id, baseline_metrics, current_metrics, target_specification):
        if "score" not in baseline_metrics or "score" not in current_metrics: return self._invalid(candidate_id,"optimized","缺少 score")
        b=float(baseline_metrics["score"]); c=float(current_metrics["score"]); t=float(target_specification.get("minimum_score",self.target_score)); delta={k:float(current_metrics[k])-float(baseline_metrics[k]) for k in set(baseline_metrics)&set(current_metrics)}
        return EvaluationResult(candidate_id,c>b+self.tolerance,c>=t,dict(baseline_metrics),dict(current_metrics),delta,c,f"score={c:.3f}, baseline={b:.3f}, target={t:.3f}")
