"""Draw a zone polygon on the first frame of a clip and save it as JSON.

Usage:
    python draw_zone.py data/clips/office_door_03.mp4 --zone-id Z1 --label "restricted door"

Left click  : add a point
u           : undo last point
s           : save and quit
q / ESC     : quit without saving

Writes data/zones/<clip_stem>.json  ->  {"zone_id", "camera_id", "polygon", "label", "version"}
Polygon coordinates are pixel coordinates in the ORIGINAL frame resolution.
"""

import argparse
import json
from pathlib import Path

import cv2

WINDOW = "draw zone - click points, 's' to save"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("clip", help="path to the video file")
    ap.add_argument("--zone-id", default="Z1")
    ap.add_argument("--label", default="restricted area")
    ap.add_argument("--camera-id", default=None, help="defaults to the clip stem")
    ap.add_argument("--out-dir", default="data/zones")
    ap.add_argument("--version", type=int, default=1)
    args = ap.parse_args()

    clip = Path(args.clip)
    cap = cv2.VideoCapture(str(clip))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise SystemExit(f"could not read the first frame of {clip}")

    points: list[list[int]] = []

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            points.append([int(x), int(y)])

    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WINDOW, on_mouse)

    while True:
        canvas = frame.copy()
        for i, p in enumerate(points):
            cv2.circle(canvas, tuple(p), 4, (0, 0, 255), -1)
            cv2.putText(canvas, str(i), (p[0] + 6, p[1] - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        if len(points) >= 2:
            cv2.polylines(canvas, [__import__("numpy").array(points)],
                          isClosed=len(points) >= 3, color=(0, 255, 0), thickness=2)
        cv2.imshow(WINDOW, canvas)

        key = cv2.waitKey(20) & 0xFF
        if key == ord("u") and points:
            points.pop()
        elif key == ord("s"):
            break
        elif key in (ord("q"), 27):
            cv2.destroyAllWindows()
            raise SystemExit("cancelled, nothing written")

    cv2.destroyAllWindows()

    if len(points) < 3:
        raise SystemExit("a polygon needs at least 3 points")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{clip.stem}.json"
    zone = {
        "zone_id": args.zone_id,
        "camera_id": args.camera_id or clip.stem,
        "polygon": points,
        "label": args.label,
        "version": args.version,
    }
    out_path.write_text(json.dumps(zone, indent=2))
    print(f"wrote {out_path} with {len(points)} points")


if __name__ == "__main__":
    main()
