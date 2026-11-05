"""Where to learn each model: real, citable works only (Zach via the coordinator, 2026-11-05).

Every DOI here was resolved at Crossref and its title matched; every URL was fetched (2xx after redirects). The check is
type_cards/check_references.py, its results type_cards/references_checked.json, and tests/test_ladders.py holds every reference
the registry uses to them. Citations carry what Crossref confirmed (authors, year, title, venue), not page numbers from memory.
Works with no stable URL (Brown 1966, ISO 9283) are cited without one.
"""

from __future__ import annotations

from .schema import Reference

R = Reference


def doi(title: str, doi_: str, note: str = "", kind: str = "paper") -> Reference:
    return Reference(title, url=f"https://doi.org/{doi_}", kind=kind, doi=doi_, note=note)


# --- friction, backlash, ripple, drives --------------------------------------------------------------------------------------
ARMSTRONG_1994 = doi("Armstrong-Hélouvry, Dupont, Canudas de Wit (1994). A survey of models, analysis tools and compensation methods for the "
                     "control of machines with friction. Automatica.", "10.1016/0005-1098(94)90209-7", "Coulomb, viscous and Stribeck friction")
CANUDAS_1995 = doi("Canudas de Wit, Olsson, Åström, Lischinsky (1995). A new model for control of systems with friction. IEEE Transactions on "
                   "Automatic Control.", "10.1109/9.376053", "LuGre: the dynamic friction model robotparts' M3.lugre is")
OLSSON_1998 = doi("Olsson, Åström, Canudas de Wit, Gäfvert, Lischinsky (1998). Friction models and friction compensation. European Journal "
                  "of Control.", "10.1016/S0947-3580(98)70113-X", "static friction models from Coulomb + viscous to Stribeck")
NORDIN_2002 = doi("Nordin, Gutman (2002). Controlling mechanical systems with backlash—a survey. Automatica.", "10.1016/S0005-1098(02)00047-X",
                  "dead-zone backlash between motor and load")
JAHNS_1996 = doi("Jahns, Soong (1996). Pulsating torque minimization techniques for permanent magnet AC motor drives—a review. IEEE "
                 "Transactions on Industrial Electronics.", "10.1109/41.491356", "cogging and commutation ripple as rotor harmonics")
TUTTLE_1996 = doi("Tuttle, Seering (1996). A nonlinear model of a harmonic drive gear transmission. IEEE Transactions on Robotics and "
                  "Automation.", "10.1109/70.499819", "a gear's compliance, friction and kinematic error")
KIRCANSKI_1997 = doi("Kircanski, Goldenberg (1997). An experimental study of nonlinear stiffness, hysteresis, and friction effects in robot "
                     "joints with harmonic drives and torque sensors. The International Journal of Robotics Research.", "10.1177/027836499701600207",
                     "load-dependent friction and torsional stiffness measured in a joint")
KRAUSE_2013 = doi("Krause, Wasynczuk, Sudhoff, Pekarek (2013). Analysis of Electric Machinery and Drive Systems, 3rd ed. Wiley-IEEE Press.",
                  "10.1002/9781118524336", "the PM machine's electrical model: R, L, back-EMF, the voltage ceiling", kind="book")
KRISHNAN_2010 = doi("Krishnan (2010). Permanent Magnet Synchronous and Brushless DC Motor Drives. CRC Press.", "10.1201/9781420014235",
                    "field-oriented current loops of PM drives", kind="book")
MOTEUS_REFERENCE = R("mjbots (2026). moteus reference manual (docs/reference.md).", "https://github.com/mjbots/moteus/blob/main/docs/reference.md",
                     kind="doc", note="the board's current loop, limits (max_voltage, max_current) and calibration")
MUJOCO_ARMATURE = R("MuJoCo (2026). XML reference: joint armature.", "https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-joint-armature",
                    kind="doc", note="the rotor's inertia reflected through the gear, as the simulator takes it")
MUJOCO_DCMOTOR = R("MuJoCo (2026). XML reference: the dcmotor actuator.", "https://mujoco.readthedocs.io/en/stable/XMLreference.html#actuator-dcmotor",
                   kind="doc", note="robotparts' M5.dcmotor: electrics, heat, cogging and LuGre as MuJoCo takes them")
MUJOCO_CONTACT = R("MuJoCo (2026). Computation: the contact model.", "https://mujoco.readthedocs.io/en/stable/computation/index.html", kind="doc",
                   note="soft contact with friction cones, what the twin's grasp runs on")
SICILIANO_2009 = doi("Siciliano, Sciavicco, Villani, Oriolo (2009). Robotics: Modelling, Planning and Control. Springer.", "10.1007/978-1-84628-642-1",
                     "rigid-body joint dynamics and reflected inertia", kind="book")

# --- identification and kinematic calibration -------------------------------------------------------------------------------------
HOLLERBACH_2016 = doi("Hollerbach, Khalil, Gautier (2016). Model identification. In Springer Handbook of Robotics, 2nd ed. Springer.",
                      "10.1007/978-3-319-32552-1_6", "kinematic calibration and inertial identification, one chapter", kind="chapter")
HOLLERBACH_WAMPLER_1996 = doi("Hollerbach, Wampler (1996). The calibration index and taxonomy for robot kinematic calibration methods. The "
                              "International Journal of Robotics Research.", "10.1177/027836499601500604", "open- and closed-loop kinematic calibration")
GAUTIER_1990 = doi("Gautier, Khalil (1990). Direct calculation of minimum set of inertial parameters of serial robots. IEEE Transactions on "
                   "Robotics and Automation.", "10.1109/70.56655", "the base inertial parameters an arm can identify")
SWEVERS_1997 = doi("Swevers, Ganseman, Tükel, De Schutter, Van Brussel (1997). Optimal robot excitation and identification. IEEE Transactions "
                   "on Robotics and Automation.", "10.1109/70.631234", "periodic excitation trajectories for dynamic identification")
ATKESON_1986 = doi("Atkeson, An, Hollerbach (1986). Estimation of inertial parameters of manipulator loads and links. The International "
                   "Journal of Robotics Research.", "10.1177/027836498600500306", "link and load inertials by least squares")
SPONG_1987 = doi("Spong (1987). Modeling and control of elastic joint robots. Journal of Dynamic Systems, Measurement, and Control.",
                 "10.1115/1.3143860", "joint compliance as a spring between motor and link")
DH_1955 = doi("Denavit, Hartenberg (1955). A kinematic notation for lower-pair mechanisms based on matrices. Journal of Applied Mechanics.",
              "10.1115/1.4011045", "the DH parameters of a serial chain")
HAYATI_1983 = doi("Hayati (1983). Robot arm geometric link parameter estimation. The 22nd IEEE Conference on Decision and Control.",
                  "10.1109/CDC.1983.269783", "modified DH for parallel axes, the form kinematic calibration fits")
OKAMURA_1996 = doi("Okamura, Park (1996). Kinematic calibration using the product of exponentials formula. Robotica.", "10.1017/S0263574700019810",
                   "a singularity-free calibration parameterisation")
UR_DH = R("Universal Robots (2026). DH parameters for calculations of kinematics and dynamics.",
          "https://www.universal-robots.com/articles/ur/application-installation/dh-parameters-for-calculations-of-kinematics-and-dynamics/",
          kind="doc", note="the UR5e's nominal DH table and masses")
ISO_9283 = R("ISO (1998). ISO 9283:1998 Manipulating industrial robots — Performance criteria and related test methods.", kind="standard",
             note="pose accuracy and repeatability (AP, RP), path accuracy (AT, RT), drift")
TSAI_1989 = doi("Tsai, Lenz (1989). A new technique for fully autonomous and efficient 3D robotics hand/eye calibration. IEEE Transactions on "
                "Robotics and Automation.", "10.1109/70.34770", "hand-eye calibration, AX = XB")
PARK_1994 = doi("Park, Martin (1994). Robot sensor calibration: solving AX=XB on the Euclidean group. IEEE Transactions on Robotics and "
                "Automation.", "10.1109/70.326576", "a closed-form AX = XB on SE(3)")
DANIILIDIS_1999 = doi("Daniilidis (1999). Hand-eye calibration using dual quaternions. The International Journal of Robotics Research.",
                      "10.1177/02783649922066213", "rotation and translation solved together")

# --- cameras ------------------------------------------------------------------------------------------------------------------
ZHANG_2000 = doi("Zhang (2000). A flexible new technique for camera calibration. IEEE Transactions on Pattern Analysis and Machine "
                 "Intelligence.", "10.1109/34.888718", "pinhole intrinsics from a planar target in several poses")
BROWN_1966 = R("Brown (1966). Decentering distortion of lenses. Photogrammetric Engineering.", kind="paper",
               note="the radial and tangential (Brown-Conrady) distortion model; no stable URL")
HEIKKILA_1997 = doi("Heikkilä, Silvén (1997). A four-step camera calibration procedure with implicit image correction. IEEE Conference on "
                    "Computer Vision and Pattern Recognition.", "10.1109/CVPR.1997.609468", "pinhole + radial and tangential distortion fitted together")
OTH_2013 = doi("Oth, Furgale, Kneip, Siegwart (2013). Rolling shutter camera calibration. IEEE Conference on Computer Vision and Pattern "
               "Recognition.", "10.1109/CVPR.2013.179", "the line delay of a rolling shutter, calibrated")
MEINGAST_2005 = R("Meingast, Geyer, Sastry (2005). Geometric models of rolling-shutter cameras. arXiv:cs/0503076.", "https://arxiv.org/abs/cs/0503076",
                  kind="preprint", note="each row exposed at its own time")
SCHOPS_2020 = doi("Schöps, Larsson, Pollefeys, Sattler (2020). Why having 10,000 parameters in your camera model is better than twelve. "
                  "IEEE/CVF Conference on Computer Vision and Pattern Recognition.", "10.1109/CVPR42600.2020.00261",
                  "a dense B-spline generic camera model above the parametric one")
KHOSHELHAM_2012 = doi("Khoshelham, Elberink (2012). Accuracy and resolution of Kinect depth data for indoor mapping applications. Sensors.",
                      "10.3390/s120201437", "depth from disparity and its error growing with z²")
HERRERA_2012 = doi("Herrera C., Kannala, Heikkilä (2012). Joint depth and color camera calibration with distortion correction. IEEE "
                   "Transactions on Pattern Analysis and Machine Intelligence.", "10.1109/TPAMI.2012.125", "depth bias as a spatially varying disparity distortion")
MOUROULIS_2000 = doi("Mouroulis, Green, Chrien (2000). Design of pushbroom imaging spectrometers for optimum recovery of spectroscopic and "
                     "spatial information. Applied Optics.", "10.1364/AO.39.002210", "smile and keystone")
KRUSE_1993 = doi("Kruse, Lefkoff, Boardman, Heidebrecht, Shapiro, Barloon, Goetz (1993). The spectral image processing system (SIPS)—interactive "
                 "visualization and analysis of imaging spectrometer data. Remote Sensing of Environment.", "10.1016/0034-4257(93)90013-N",
                 "the spectral angle")
GUPTA_1997 = doi("Gupta, Hartley (1997). Linear pushbroom cameras. IEEE Transactions on Pattern Analysis and Machine Intelligence.",
                 "10.1109/34.615446", "the line-scan (pushbroom) camera's geometry")
BURGER_2011 = doi("Burger, Gowen (2011). Data handling in hyperspectral image analysis. Chemometrics and Intelligent Laboratory Systems.",
                  "10.1016/j.chemolab.2011.04.001", "dark and white reference reflectance calibration")

# --- encoders ---------------------------------------------------------------------------------------------------------------
WIDROW_2008 = doi("Widrow, Kollár (2008). Quantization Noise. Cambridge University Press.", "10.1017/CBO9780511754661", "an encoder as a quantiser",
                  kind="book")
MERRY_2010 = doi("Merry, van de Molengraft, Steinbuch (2010). Velocity and acceleration estimation for optical incremental encoders. "
                 "Mechatronics.", "10.1016/j.mechatronics.2009.06.010", "encoder noise, quantisation and delay in velocity")
ZHAO_2024 = doi("Zhao, Wan, Liang (2024). Automatic compensation system for eccentricity error of absolute optical encoder. Review of "
                "Scientific Instruments.", "10.1063/5.0211297", "eccentricity as once-per-turn harmonics")

# --- conveyors and grasping -------------------------------------------------------------------------------------------------------
ZHANG_XIA_2011 = doi("Zhang, Xia (2011). Modeling and energy efficiency optimization of belt conveyors. Applied Energy.",
                     "10.1016/j.apenergy.2011.03.015", "a belt conveyor's resistances and drive power")
HE_2017 = doi("He, Pang, Lodewijks (2017). Green operations of belt conveyors by means of speed control. Applied Energy.",
              "10.1016/j.apenergy.2016.12.017", "a belt conveyor's dynamics under speed changes")
PRATTICHIZZO_2016 = doi("Prattichizzo, Trinkle (2016). Grasping. In Springer Handbook of Robotics, 2nd ed. Springer.", "10.1007/978-3-319-32552-1_38",
                        "contact, friction cones and grasp force", kind="chapter")

# --- wear --------------------------------------------------------------------------------------------------------------------
ARCHARD_1953 = doi("Archard (1953). Contact and rubbing of flat surfaces. Journal of Applied Physics.", "10.1063/1.1721448",
                   "wear volume grows with the load carried times the distance slid")
FLODIN_1997 = doi("Flodin, Andersson (1997). Simulation of mild wear in spur gears. Wear.", "10.1016/S0043-1648(96)07467-4",
                  "Archard's law on gear teeth: the flank wear that opens backlash")
LU_MEEKER_1993 = doi("Lu, Meeker (1993). Using degradation measures to estimate a time-to-failure distribution. Technometrics.",
                     "10.1080/00401706.1993.10485038", "a degradation path in usage, linear the simplest, crossing a failure threshold")
MEEKER_1998 = doi("Meeker, Escobar, Lu (1998). Accelerated degradation tests: modeling and analysis. Technometrics.", "10.1080/00401706.1998.10485191",
                  "degradation paths fitted and extrapolated to a threshold")
WHITMORE_1995 = doi("Whitmore (1995). Estimating degradation by a Wiener diffusion process subject to measurement error. Lifetime Data Analysis.",
                    "10.1007/BF00985762", "diffusive drift: its expected size grows as the square root of time")
JUNKER_1969 = doi("Junker (1969). New criteria for self-loosening of fasteners under vibration. SAE Technical Paper.", "10.4271/690055",
                  "a mount loosening under transverse vibration")

# --- learned models ----------------------------------------------------------------------------------------------------------------
HWANGBO_2019 = doi("Hwangbo, Lee, Dosovitskiy, Bellicoso, Tsounis, Koltun, Hutter (2019). Learning agile and dynamic motor skills for legged "
                   "robots. Science Robotics.", "10.1126/scirobotics.aau5872",
                   "ANYmal's actuator net: an MLP over position error and velocity at t, t − 10 ms, t − 20 ms, 3 × 32 softsign (arXiv:1901.08652)")
HWANGBO_2019_ARXIV = R("Hwangbo, Lee, Dosovitskiy, Bellicoso, Tsounis, Koltun, Hutter (2019). Learning agile and dynamic motor skills for legged "
                       "robots. arXiv:1901.08652.", "https://arxiv.org/abs/1901.08652", kind="preprint", note="the open version")
NGUYEN_TUONG_2010 = doi("Nguyen-Tuong, Peters (2010). Using model knowledge for learning inverse dynamics. IEEE International Conference on "
                        "Robotics and Automation.", "10.1109/ROBOT.2010.5509858", "a physics model plus a learned residual")
ZENG_2020 = doi("Zeng, Song, Lee, Rodriguez, Funkhouser (2020). TossingBot: learning to throw arbitrary objects with residual physics. IEEE "
                "Transactions on Robotics.", "10.1109/TRO.2020.2988642", "residual physics: learn what the physics estimate misses")
KOVALEV_2026 = R("Kovalev, Chaikovskaia, Davydenko, Gorbachev et al. (2026). Trajectory-based actuator identification via differentiable "
                 "simulation. arXiv:2604.10351.", "https://arxiv.org/abs/2604.10351", kind="preprint",
                 note="a structured servo fit vs an MLP vs a residual model on held-out position error")
ZHU_2025 = R("Zhu, Tanaka, Rafeedi, Hong (2025). Cycloidal quasi-direct drive actuator designs with learning-based torque estimation for legged "
             "robotics. arXiv:2410.16591.", "https://arxiv.org/abs/2410.16591", kind="preprint",
             note="a longer history (a 30-step GRU) when ripple or backlash matter")

WEAR_LAW_REFERENCES = {
    "linear": (LU_MEEKER_1993, MEEKER_1998),
    "sqrt": (WHITMORE_1995, JUNKER_1969),
    "archard": (ARCHARD_1953, FLODIN_1997),
}

ALL = tuple(v for k, v in sorted(globals().items()) if isinstance(v, Reference))
