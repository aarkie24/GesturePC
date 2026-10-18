"""Unit tests for ExecutionGate safety boundaries and admission token semantics."""

import concurrent.futures
from services.execution_gate import ExecutionGate


def test_gate_initial_state():
    gate = ExecutionGate()
    assert not gate.is_open
    assert gate.epoch == 0
    assert gate.admit() is None
    assert not gate.is_current(None)


def test_gate_lifecycle_and_admissions():
    gate = ExecutionGate()

    # Open for live
    epoch1 = gate.open_for_live()
    assert gate.is_open
    assert epoch1 == 1

    adm1 = gate.admit()
    assert adm1 is not None
    assert adm1.epoch == 1
    assert gate.is_current(adm1)

    # Close gate
    epoch2 = gate.close("USER_STOP")
    assert not gate.is_open
    assert epoch2 == 2
    assert gate.close_reason == "USER_STOP"

    # Old admission is immediately invalid
    assert not gate.is_current(adm1)

    # No new admissions while closed
    assert gate.admit() is None

    # Re-opening creates new epoch
    epoch3 = gate.open_for_live()
    assert epoch3 == 3
    adm2 = gate.admit()
    assert adm2 is not None
    assert adm2.epoch == 3
    assert gate.is_current(adm2)
    # adm1 is still invalid
    assert not gate.is_current(adm1)


def test_gate_multithreaded_stress():
    gate = ExecutionGate()
    gate.open_for_live()

    admissions = []
    stop_signal = False

    def admit_worker():
        while not stop_signal:
            adm = gate.admit()
            if adm is not None:
                admissions.append(adm)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(admit_worker) for _ in range(3)]
        # Concurrently close the gate
        gate.close("STRESS_TEST")
        stop_signal = True
        for f in futures:
            f.result()

    # After close, no recorded admission may evaluate to is_current
    for adm in admissions:
        assert not gate.is_current(adm)
