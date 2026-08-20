from __future__ import annotations


def assign_boundaries_and_ports(hfss, include_radiation_region=False):
    """Assign all boundaries by stable object name and explicit coordinates."""
    hfss.assign_perfect_e("Rectangle6", name="PerfE3")
    hfss.assign_perfect_e("Rectangle8", name="PerfE4")

    # Keep both integration lines centered on their parameterized port sheets.
    # PyAEDT expects numeric model-unit coordinates for integration lines, so
    # evaluate the AEDT expressions and convert the returned SI values to mm.
    def point_in_mm(expressions):
        return [hfss.evaluate_expression(expression) * 1000.0 for expression in expressions]

    output_x = "x1+signal_l4-signal_w2"
    output_y = "y1-signal_l3+signal_l5"
    output_z = "-rdl_h-h2_sio2-h_pi-2*(r_bga-delta_bga)-2*h_pi-rdl_h-h_sio2-rdl_h"
    output_line = [
        point_in_mm([output_x, output_y, output_z + "-port_h"]),
        point_in_mm([output_x, output_y, output_z]),
    ]
    input_x = "inter_w/2"
    input_y = "-inter_l/2+l1-pad_w/2-signal_w1/2+pad_w1/2"
    input_z = "inter_h-rdl_h"
    input_line = [
        point_in_mm([input_x, input_y, input_z + "-port_h"]),
        point_in_mm([input_x, input_y, input_z]),
    ]
    port_3 = hfss.lumped_port("Rectangle4", integration_line=output_line, name="3", impedance=50)
    port_4 = hfss.lumped_port("Rectangle1", integration_line=input_line, name="4", impedance=50)
    if not port_3 or not port_4:
        raise RuntimeError("Failed to create lumped ports 3 and 4")
    if include_radiation_region:
        hfss.assign_radiation_boundary_to_objects("RadiatingSurface", name="AutoOpen1")


def create_analysis(hfss, progress_callback=None, stage_prefix="design"):
    setup = hfss.create_setup(
        name="Setup1",
        setup_type="HFSSDriven",
        Frequency="10GHz",
        MaxDeltaS=0.02,
        MaximumPasses=6,
        MinimumPasses=1,
        MinimumConvergedPasses=1,
        PercentRefinement=30,
        BasisOrder=1,
    )
    if not setup:
        raise RuntimeError("Failed to create HFSS setup Setup1")
    if progress_callback:
        progress_callback(stage_prefix + ":setup:complete")

    # Use the setup object returned above instead of making the application
    # enumerate every setup again.  The latter can stall in PyAEDT 0.18.1
    # after a large geometry build because it reparses the design cache.
    sweep = setup.create_linear_step_sweep(
        unit="GHz",
        start_frequency=0.1,
        stop_frequency=20,
        step_size=0.1,
        name="Sweep",
        save_fields=True,
        sweep_type="Fast",
    )
    if not sweep:
        raise RuntimeError("Failed to create HFSS frequency sweep Sweep")
    if progress_callback:
        progress_callback(stage_prefix + ":sweep:complete")

    # Candidate variation belongs to the Agent optimizer.  A second, disabled
    # Optimetrics sweep inside HFSS is unused by this workflow and is omitted.
    return setup


def create_reports(hfss):
    solution = "Setup1 : Sweep"
    for name, expression in (
        ("S Parameter Plot 4", "dB(S(3,3))"),
        ("S Parameter Plot 5", "dB(S(4,3))"),
        ("S Parameter Plot 6", "dB(S(3,3))"),
    ):
        hfss.post.create_report(
            expression,
            setup_sweep_name=solution,
            report_category="Modal Solution Data",
            plot_name=name,
        )
