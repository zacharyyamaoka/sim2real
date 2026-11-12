"""CAN 11 on the One Dof Test Rack swung as a pendulum: calibrate the servo's model against the simulator's sealed hidden truth."""

import sim2real

if __name__ == "__main__":  # calibrate() replays runs in a process pool that re-imports this module
    twin = sim2real.examples.pendulum_can11()
    fitted = twin.calibrate(on="sim")
    print(fitted.summary())
    report = fitted.eval()
    print(report.summary())
