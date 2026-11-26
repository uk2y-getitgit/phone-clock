"""배경 이미지(web/bg.svg) 생성기 — 점으로 된 지구본 + 네트워크 선 + 네온 링.
값을 바꾼 뒤 `python tools/make_bg.py` 로 다시 만들 수 있습니다."""
import math
import os
import random

W, H = 2000, 1000
CX, CY, R = 700, 560, 420          # 지구본 위치/크기
TILT = math.radians(-18)           # 위아래 기울기
SPIN = math.radians(-115)          # 아시아가 정면에 오도록 회전
random.seed(7)

# 대륙 대략 위치 (위도, 경도, 반지름°) — 점 밀도를 높여 대륙처럼 보이게 함
LAND = [
    (50, 90, 28), (60, 120, 22), (45, 60, 18), (35, 105, 18), (28, 80, 10), (22, 78, 9),
    (15, 102, 8), (5, 110, 6), (-2, 115, 7), (37, 128, 3), (37, 138, 4), (63, 160, 12),
    (50, 20, 14), (60, 40, 14), (25, 45, 10), (8, 20, 18), (-10, 25, 15), (-25, 25, 9),
    (-25, 134, 14), (-6, 145, 5), (65, 100, 18),
]


def is_land(lat, lon):
    for la, lo, rr in LAND:
        d = math.degrees(math.acos(max(-1, min(1,
            math.sin(math.radians(lat)) * math.sin(math.radians(la)) +
            math.cos(math.radians(lat)) * math.cos(math.radians(la)) * math.cos(math.radians(lon - lo))))))
        if d < rr * (0.85 + 0.3 * math.sin(lat * 0.7 + lon * 0.5)):
            return True
    return False


def project(lat, lon, rad=R):
    la, lo = math.radians(lat), math.radians(lon) + SPIN
    x, y, z = math.cos(la) * math.sin(lo), math.sin(la), math.cos(la) * math.cos(lo)
    y, z = y * math.cos(TILT) - z * math.sin(TILT), y * math.sin(TILT) + z * math.cos(TILT)
    return CX + rad * x, CY - rad * y, z


out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid slice">',
       '<defs>',
       '<radialGradient id="sky" cx="35%" cy="58%" r="75%"><stop offset="0" stop-color="#0a2350"/>'
       '<stop offset=".55" stop-color="#050f26"/><stop offset="1" stop-color="#02050e"/></radialGradient>',
       '<radialGradient id="globe" cx="45%" cy="40%" r="60%"><stop offset="0" stop-color="#1c5fb8" stop-opacity=".55"/>'
       '<stop offset=".7" stop-color="#0b2b63" stop-opacity=".35"/><stop offset="1" stop-color="#0b2b63" stop-opacity="0"/></radialGradient>',
       '<radialGradient id="halo" cx="50%" cy="50%" r="50%"><stop offset=".78" stop-color="#2f8cff" stop-opacity="0"/>'
       '<stop offset=".86" stop-color="#2f8cff" stop-opacity=".22"/><stop offset="1" stop-color="#2f8cff" stop-opacity="0"/></radialGradient>',
       '<radialGradient id="node"><stop offset="0" stop-color="#bfe6ff"/><stop offset=".35" stop-color="#46b4ff" stop-opacity=".7"/>'
       '<stop offset="1" stop-color="#46b4ff" stop-opacity="0"/></radialGradient>',
       '<filter id="soft"><feGaussianBlur stdDeviation="1.2"/></filter>',
       '</defs>',
       f'<rect width="{W}" height="{H}" fill="url(#sky)"/>']

# 별 (아주 희미하게)
for _ in range(160):
    x, y = random.uniform(0, W), random.uniform(0, H)
    out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{random.uniform(.6, 1.6):.1f}" fill="#9fd0ff" opacity="{random.uniform(.08, .35):.2f}"/>')

# 지구본 본체 + 테두리 빛
out.append(f'<circle cx="{CX}" cy="{CY}" r="{R * 1.22:.0f}" fill="url(#halo)"/>')
out.append(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="url(#globe)"/>')
out.append(f'<circle cx="{CX}" cy="{CY}" r="{R}" fill="none" stroke="#5ab8ff" stroke-opacity=".35" stroke-width="2"/>')

# 점 지구본
dots = []
lat = -84.0
while lat <= 84:
    n = max(8, int(360 * math.cos(math.radians(lat)) / 2.6))
    for i in range(n):
        lon = i * 360 / n
        x, y, z = project(lat, lon)
        if z < 0.02:
            continue
        shade = 0.25 + 0.75 * z
        if is_land(lat, lon):
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{2.1 + 1.3 * z:.1f}" fill="#7fd0ff" opacity="{.75 * shade:.2f}"/>')
        else:
            dots.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{1.1 + .6 * z:.1f}" fill="#3a8fe0" opacity="{.28 * shade:.2f}"/>')
    lat += 2.6
out.append('<g>' + ''.join(dots) + '</g>')

# 네트워크(플렉서스) — 지구 바깥 껍질 위의 점들을 선으로 연결
nodes = []
for _ in range(46):
    la, lo = math.degrees(math.asin(random.uniform(-.95, .95))), random.uniform(0, 360)
    x, y, z = project(la, lo, R * random.uniform(1.08, 1.32))
    if z > -0.35:
        nodes.append((x, y, z))
lines = []
for i, a in enumerate(nodes):
    near = sorted(nodes[i + 1:], key=lambda b: (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)[:3]
    for b in near:
        d = math.hypot(a[0] - b[0], a[1] - b[1])
        if d < R * 0.75:
            op = .10 + .22 * (min(a[2], b[2]) + .35)
            lines.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="#4fb4ff" stroke-opacity="{op:.2f}" stroke-width="1.3"/>')
out.append('<g>' + ''.join(lines) + '</g>')
for x, y, z in nodes:
    s = 7 + 6 * (z + .35)
    out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{s:.0f}" fill="url(#node)" opacity="{.45 + .4 * (z + .35) / 1.35:.2f}"/>')

# 오른쪽 아래로 흐르는 네온 링 (참고 이미지의 원형 아이콘 자리)
for k in range(9):
    t = k / 8
    x = 1180 + 760 * t
    y = 860 - 300 * math.sin(t * math.pi * .55) + 40 * t
    r = 26 + 12 * math.sin(t * math.pi)
    out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.0f}" fill="#0c2a5c" fill-opacity=".25" stroke="#5ab8ff" stroke-opacity=".35" stroke-width="2"/>')
    out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r * .45:.0f}" fill="none" stroke="#9fd8ff" stroke-opacity=".25" stroke-width="1.5"/>')
out.append('<path d="M1120 900 Q 1550 560 2000 600" fill="none" stroke="#3fa9ff" stroke-opacity=".18" stroke-width="2" filter="url(#soft)"/>')

# 아래쪽 수평선 빛
out.append(f'<ellipse cx="{W * .5:.0f}" cy="{H + 60}" rx="{W * .7:.0f}" ry="140" fill="#1f6fff" opacity=".12" filter="url(#soft)"/>')
out.append('</svg>')

dst = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "bg.svg")
with open(dst, "w", encoding="utf-8") as f:
    f.write("\n".join(out))
print("saved", dst, os.path.getsize(dst) // 1024, "KB")
