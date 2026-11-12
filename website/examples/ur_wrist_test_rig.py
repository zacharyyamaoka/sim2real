"""The UR wrist test rig: three servos, one-click calibrate() on the rig's routines, then held-out evaluation."""

import sim2real

if __name__ == "__main__":  # calibrate() replays runs in a process pool that re-imports this module
    twin = sim2real.examples.ur_wrist_test_rig()
    fitted = twin.calibrate(on="sim")
    print(fitted.summary())
    report = fitted.eval()
    print(report.summary())
