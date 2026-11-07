"""The One Dof Test Rack's v3 record: its declared tags and its cameras (app/registry.json holds the rest)."""

from type_cards.domain import CameraDecl, PhysicalDeployment

VIEW = "bam_ws src/dev/bam_rack_twin/docs/dataset_clips.py VIEW (the camera and the tag that see each CAN id); bam_rack_twin/trajectory_dataset.py CAMERAS"

record = PhysicalDeployment(
    id="one-dof-test-rack",
    tags=(),
    cameras=(
        CameraDecl(
            serial="218622274411",
            model="Intel RealSense D405",
            type="depth_camera",
            sees=(1, 14, 15, 4, 21),
            source=VIEW + "; tags 0, 1, 2, 4, 5",
        ),
        CameraDecl(
            serial="218622276036",
            model="Intel RealSense D405",
            type="depth_camera",
            sees=(13, 12, 11),
            source=VIEW + "; tags 6, 7, 8",
        ),
    ),
    note="The D435 044322072026 RobotDx lists on the same host is not here: no bam_rack_twin map ties it to a station.",
)
