from __future__ import annotations

import re


DESIGN_PARAMETERS = {
    "inter_w": "4mm",
    "inter_l": "4mm",
    "inter_h": "0.2mm",
    "rdl_h": "5um",
    "pad_w": "0.12mm",
    "d1": "2mm",
    "pad_d": "0.05mm",
    "h_sio2": "3um",
    "signal_l1": "2.2mm",
    "h2_sio2": "3um",
    "r_fm1": "35um",
    "h_pi": "12um",
    "r_tsv": "15um",
    "signal_w1": "0.1mm",
    "signal_d1": "0.05mm",
    "l1": "2.5mm",
    "signal_l2": "-0.5mm",
    "r_ubm": "0.1mm",
    "l2": "0.08mm",
    "r_bga": "125um",
    "delta_bga": "25um",
    "h1_bga": "r_bga-delta_bga",
    "port_h": "30um",
    "pad_w1": "0.1mm",
    "delta_d": "50um",
    "signal_l3": "0.75mm",
    "r1": "0.05mm",
    "r2": "0.19mm",
    "distence_ubm": "0.7mm",
    "r3": "0.15mm",
    "inter_w2": "8mm",
    "inter_l2": "3mm+inter2_y",
    "r4": "0.05mm",
    "r5": "r4",
    "distence_tsv": "0.1mm",
    "distence_tsv1": "0.13mm",
    "offset_tsv_line": "0.26mm",
    "offset_ubm_ubm": "0.66mm",
    "signal_w2": "0.08mm",
    "signal_l4": "4.295mm",
    "signal_l5": "0.63mm",
    "signal_d2": "0.05mm",
    "r_inter2_fm2": "r2",
    "inter2_y": "inter_l/2-y1",
    "inter2_x": "-inter_w/2-x1",
    "offset_inter2": "3mm",
    "pad_w2": "0.09mm",
    "l3": "l1-pad_w/2-signal_w1/2",
    "r_inter1_fm2": "r2",
    "r_inter1_fm2_gnd": "r2",
    "inter_h1": "0.1mm",
    "inter_w3": "4mm",
    "x1": "inter_w/2-pad_w1-delta_d-signal_l1",
    "y1": "-inter_l/2+l3+signal_w1/2",
    "delta_x": "300um",
    "delta_y": "500um",
}


def apply_parameters(hfss, overrides=None):
    """Apply the exact 56 source-design variables in dependency-safe order."""
    pending = dict(DESIGN_PARAMETERS)
    overrides = overrides or {}
    unknown = set(overrides) - set(pending)
    if unknown:
        raise ValueError("Unknown design parameters: %s" % ", ".join(sorted(unknown)))
    pending.update(overrides)
    created = set()
    identifier = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
    while pending:
        progressed = False
        for name, expression in list(pending.items()):
            dependencies = {token for token in identifier.findall(expression) if token in DESIGN_PARAMETERS}
            if dependencies.issubset(created):
                hfss[name] = expression
                created.add(name)
                del pending[name]
                progressed = True
        if not progressed:
            raise RuntimeError("Cyclic or unresolved parameter dependencies: %r" % pending)
    assert len(DESIGN_PARAMETERS) == 56
