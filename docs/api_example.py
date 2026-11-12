import sim2real

twin = sim2real.examples.pendulum_can11()        # or: description.to_robot_twin()
twin.simulate()
fitted = twin.calibrate(on="sim")
print(fitted.eval().summary())
parameters = fitted.parameters                   # what description.from_robot_twin(fitted) takes (robot_description side: not built yet)
