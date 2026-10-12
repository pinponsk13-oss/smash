# -*- coding: utf-8 -*-
"""
タッチ操作 3Dスマブラ風ゲーム  (PythonIDE / pygame 版)
=====================================================
pygame だけで動く自作3Dレンダラー(遠近法+ポリゴン描画)です。

【操作】(横向き推奨)
  画面の左半分をタッチ ........ 仮想スティック(触った場所が中心)
  攻撃(A) ...... ニュートラル=弱(3段) / 上=上強 / 下=下強 / 横=横強 / 空中=空N
  必殺(B) ...... ニュートラル=ファイアボール / 横=マント
                 上=スーパージャンプパンチ / 下=ポンプ(F.L.U.D.D.)
  ジャンプ ..... 長押し=大ジャンプ / 空中でもう1回=2段ジャンプ
  右上 RESTART . 最初から
  (キーボード) 矢印/WASD=スティック J=攻撃 K=必殺 SPACE=ジャンプ ESC=終了

文字化け(□)する場合は FORCE_ENGLISH = True にしてください。
"""
import math, random, time, sys, os
import pygame

TAU = math.pi * 2
DT = 1.0 / 60.0
SHOW_HITBOX = False          # True にすると攻撃判定を表示
FORCE_ENGLISH = False        # True にすると表示を英語にする

# ---------------- ステージ(終点) ----------------
STAGE_HW = 68.0              # さらに広いメインステージ
STAGE_DZ = 16.0
# 小戦場風のすり抜け床(x位置、床の高さ、横半幅、奥行き半幅)
PLATFORMS = ((-20.0, 20.5, 10.0, 8.0), (20.0, 20.5, 10.0, 8.0))  # キャラの頭より少し高い位置
BODY_T = 6.0                 # 当たり判定の厚み
BLAST_L, BLAST_R, BLAST_T, BLAST_B = -220.0, 220.0, 190.0, -110.0  # 横・上の撃墜ラインを広げる

# ---------------- 物理(1フレーム=1/60秒, 本家に近い値) ----------------
GRAV = 0.095
FALL_MAX = 1.5
FAST_FALL = 2.4
JUMP_V = 2.6
DJUMP_V = 2.4
RUN_V = 1.76
WALK_V = 1.0
AIR_MAX = 1.05
KB_DECAY = 0.051             # 吹っ飛び速度の減衰/フレーム
CHAR_H = 18.0
CHAR_HW = 3.0


def approach(v, t, a):
    if v < t:
        return min(t, v + a)
    return max(t, v - a)


def sgn(v):
    return 1 if v >= 0 else -1


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


# ---------------- 3D 行列 ----------------
IDENT = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0)


def rz(a):
    c = math.cos(a); s = math.sin(a)
    return (c, -s, 0.0, s, c, 0.0, 0.0, 0.0, 1.0)


def ry(a):
    c = math.cos(a); s = math.sin(a)
    return (c, 0.0, s, 0.0, 1.0, 0.0, -s, 0.0, c)


def mm(A, B):
    return (A[0]*B[0]+A[1]*B[3]+A[2]*B[6], A[0]*B[1]+A[1]*B[4]+A[2]*B[7], A[0]*B[2]+A[1]*B[5]+A[2]*B[8],
            A[3]*B[0]+A[4]*B[3]+A[5]*B[6], A[3]*B[1]+A[4]*B[4]+A[5]*B[7], A[3]*B[2]+A[4]*B[5]+A[5]*B[8],
            A[6]*B[0]+A[7]*B[3]+A[8]*B[6], A[6]*B[1]+A[7]*B[4]+A[8]*B[7], A[6]*B[2]+A[7]*B[5]+A[8]*B[8])


def mv(R, v):
    return (R[0]*v[0]+R[1]*v[1]+R[2]*v[2],
            R[3]*v[0]+R[4]*v[1]+R[5]*v[2],
            R[6]*v[0]+R[7]*v[1]+R[8]*v[2])


def child(T, ang, off):
    """親フレームTの中で、offに関節を置き、z軸まわりにang回転した子フレーム"""
    R, t = T
    o = mv(R, off)
    return (mm(R, rz(ang)), (t[0]+o[0], t[1]+o[1], t[2]+o[2]))


# 立方体の面
def _ci(sx, sy, sz):
    return (4 if sx > 0 else 0) | (2 if sy > 0 else 0) | (1 if sz > 0 else 0)


FACES = []
for _ax in range(3):
    for _sg in (1, -1):
        _n = [0, 0, 0]; _n[_ax] = _sg
        _o = [i for i in range(3) if i != _ax]
        _idx = []
        for (_u, _v) in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            _s = [0, 0, 0]; _s[_ax] = _sg; _s[_o[0]] = _u; _s[_o[1]] = _v
            _idx.append(_ci(*_s))
        FACES.append((tuple(_n), tuple(_idx)))

_ll = math.sqrt(0.35**2 + 0.8**2 + 0.5**2)
LX, LY, LZ = -0.35/_ll, 0.8/_ll, 0.5/_ll


class Cam:
    def __init__(s):
        s.tx = 0.0; s.ty = 14.0; s.dist = 205.0; s.pitch = 0.17
        s.ox = 0.0; s.oy = 0.0
        s.setup(1024, 768)

    def setup(s, W, H):
        s.W = W; s.H = H
        s.cp = math.cos(s.pitch); s.sp = math.sin(s.pitch)
        s.cx = s.tx; s.cy = s.ty + s.sp*s.dist; s.cz = s.cp*s.dist
        s.fl = min(W, H*1.33) * 0.85

    def proj(s, x, y, z):
        dx = x - s.cx; dy = y - s.cy; dz = z - s.cz
        depth = -dy*s.sp - dz*s.cp
        if depth < 1.0:
            depth = 1.0
        yc = dy*s.cp - dz*s.sp
        k = s.fl / depth
        return (s.W*0.5 + s.ox + dx*k, s.H*0.45 + s.oy - yc*k, depth)


def add_box(polys, cam, T, c, h, col):
    R, t = T
    wc = []; pr = []
    for i in range(8):
        lx = c[0] + (h[0] if i & 4 else -h[0])
        ly = c[1] + (h[1] if i & 2 else -h[1])
        lz = c[2] + (h[2] if i & 1 else -h[2])
        wx = R[0]*lx + R[1]*ly + R[2]*lz + t[0]
        wy = R[3]*lx + R[4]*ly + R[5]*lz + t[1]
        wz = R[6]*lx + R[7]*ly + R[8]*lz + t[2]
        wc.append((wx, wy, wz))
        pr.append(cam.proj(wx, wy, wz))
    for n, idx in FACES:
        nx = R[0]*n[0] + R[1]*n[1] + R[2]*n[2]
        ny = R[3]*n[0] + R[4]*n[1] + R[5]*n[2]
        nz = R[6]*n[0] + R[7]*n[1] + R[8]*n[2]
        v = wc[idx[0]]
        if (cam.cx-v[0])*nx + (cam.cy-v[1])*ny + (cam.cz-v[2])*nz <= 0:
            continue
        lam = nx*LX + ny*LY + nz*LZ
        sh = 0.6 + 0.4*(lam if lam > 0 else 0.0)
        a = pr[idx[0]]; b = pr[idx[1]]; c2 = pr[idx[2]]; d = pr[idx[3]]
        polys.append(((a[2]+b[2]+c2[2]+d[2])*0.25,
                      ((a[0], a[1]), (b[0], b[1]), (c2[0], c2[1]), (d[0], d[1])),
                      (col[0]*sh, col[1]*sh, col[2]*sh, 1.0)))


def poly3(cam, pts, col, ctr, out):
    p0, p1, p2 = pts[0], pts[1], pts[2]
    ux, uy, uz = p1[0]-p0[0], p1[1]-p0[1], p1[2]-p0[2]
    vx, vy, vz = p2[0]-p0[0], p2[1]-p0[1], p2[2]-p0[2]
    nx = uy*vz - uz*vy; ny = uz*vx - ux*vz; nz = ux*vy - uy*vx
    if nx*(p0[0]-ctr[0]) + ny*(p0[1]-ctr[1]) + nz*(p0[2]-ctr[2]) < 0:
        nx, ny, nz = -nx, -ny, -nz
    if nx*(cam.cx-p0[0]) + ny*(cam.cy-p0[1]) + nz*(cam.cz-p0[2]) <= 0:
        return
    ln = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
    lam = (nx*LX + ny*LY + nz*LZ) / ln
    sh = 0.65 + 0.35*(lam if lam > 0 else 0.0)
    pr = [cam.proj(*q) for q in pts]
    out.append((sum(q[2] for q in pr)/len(pr), [(q[0], q[1]) for q in pr],
                (col[0]*sh, col[1]*sh, col[2]*sh, 1.0)))


def star_pts(cx, cy, r, n=8, inner=0.4, rot=0.0):
    pts = []
    for i in range(n*2):
        a = rot + i*math.pi/n
        rr = r if i % 2 == 0 else r*inner
        pts.append((cx + math.cos(a)*rr, cy + math.sin(a)*rr))
    return pts


# ====================================================================
#  モーション(ポーズ)
#  角度[rad]: 0=腕/脚が真下, +で前方へ振る / lean,head は + で前傾
#  aF,aB=肩 eF,eB=肘 lF,lB=股関節 kF,kB=膝(マイナスで後ろに曲がる)
# ====================================================================
DEF = dict(lean=0.06, head=0.0, aF=0.3, aB=-0.25, eF=0.9, eB=0.8,
           lF=0.2, lB=-0.2, kF=-0.2, kB=-0.2, dy=-0.2, dx=0.0, flip=0.0, spin=0.0)


def K(fr, **kw):
    return (fr, dict(DEF, **kw))


def interp(keys, af):
    if af <= keys[0][0]:
        return keys[0][1]
    for i in range(1, len(keys)):
        f1, p1 = keys[i]
        if af <= f1:
            f0, p0 = keys[i-1]
            u = (af - f0) / float(max(1, f1 - f0))
            return {k: p0[k] + (p1[k]-p0[k])*u for k in p0}
    return keys[-1][1]


def H(s, e, x, y, r, d, a, b, g, **kw):
    """攻撃判定: 発生s~終了e / 前方x 高さy 半径r / ダメージd 角度a 固定吹っ飛びb 吹っ飛び成長g"""
    return dict(s=s, e=e, x=x, y=y, r=r, d=d, a=a, b=b, g=g, **kw)


# ---- 技ごとの特殊処理 ----
class Fireball:
    def __init__(s, x, y, d, owner):
        s.x = x; s.y = y; s.vx = 1.55*d; s.vy = 0.0
        s.owner = owner; s.life = 110; s.r = 3.2; s.refl = False


def hk_fireball(f, af, g):
    if af == 13:
        g.fireballs.append(Fireball(f.x + f.face*7.5, f.y + 10.5, f.face, f))


def hk_cape(f, af, g):
    if af == 4 and not f.grounded:
        f.vy = max(f.vy, 0.8)
    if 4 <= af <= 18:
        g.reflect(f)


def hk_upb(f, af, g):
    if af == 3:
        f.grounded = False
        f.vy = 2.7
        f.vx = f.face*0.4 + clamp(f.inp.x, -1, 1)*0.5
        g.puff(f.x, f.y)
    if 3 <= af <= 22:
        f.gscale = 0.0
        f.vy = 2.7 - (af-3)*0.09
        f.vx = approach(f.vx, clamp(f.inp.x, -1, 1)*1.2, 0.1)
        c = f.carry
        if c is not None and c.state == 'hit' and c.carried_by is f and af < 20:
            c.x += (f.x + f.face*4.0 - c.x)*0.45
            c.y += (f.y + 4.0 - c.y)*0.45
            c.kbx = 0.0; c.kby = 0.0; c.vy = 0.0
            c.stun = max(c.stun, 4)


def hk_fludd(f, af, g):
    if not f.grounded:
        f.gscale = 0.15
        f.vy = max(f.vy, -0.35)
    if 8 <= af <= 44:
        for _ in range(2):
            g.fx.append(dict(k='water', x=f.x + f.face*7, y=f.y + 9.0,
                             vx=f.face*(2.4 + random.random()*0.8),
                             vy=random.uniform(-0.2, 0.35), life=14, max=14))
        o = g.other(f)
        if (o.state != 'dead' and o.inv <= 0 and o.plat <= 0 and
                0 < (o.x - f.x)*f.face < 40 and abs((o.y + 8) - (f.y + 9)) < 12):
            o.x += f.face*0.6


# ---- 技データ(スマブラのマリオ風) ----
PUNCH_F = dict(lean=.30, aF=1.57, eF=0.0, aB=-.7, eB=.9, lF=.7, kF=-.5, lB=-.6, kB=-.1, dx=2.0)
PUNCH_B = dict(lean=.30, aB=1.57, eB=0.0, aF=-.7, eF=.9, lF=-.6, kF=-.1, lB=.7, kB=-.5, dx=2.0)
KICK_J3 = dict(lean=-.25, lF=1.5, kF=-.05, lB=-.3, kB=-.3, aF=-.6, aB=1.2, eB=.6, dx=2.5)
KICK_FT = dict(lean=-.35, lF=1.55, kF=0.0, lB=-.1, kB=-.2, aF=-.4, aB=1.3, eB=.4, dx=2.5)
CROUCH = dict(dy=-3.1, lean=.35, lF=1.1, kF=-2.0, lB=1.1, kB=-2.0, aF=.9, aB=.7, eF=1.2, eB=1.2)

ATTACKS = {
    'jab1': dict(jp='弱攻撃①(パンチ)', len=18, chain=(2, 11, 11), next='jab2',
                 hits=[H(3, 5, 7, 10, 4.5, 2, 361, 5, 25)],
                 keys=[K(0), K(2, lean=.15, aF=1.0, eF=1.5, aB=-.4, lF=.45, kF=-.5, lB=-.45, dx=.5),
                       K(4, **PUNCH_F), K(8, **PUNCH_F), K(16)]),
    'jab2': dict(jp='弱攻撃②(パンチ)', len=18, chain=(2, 11, 11), next='jab3',
                 hits=[H(3, 5, 7, 10, 4.5, 2, 361, 5, 25)],
                 keys=[K(0, **PUNCH_F), K(2, lean=.15, aB=1.0, eB=1.5, aF=-.4, lF=-.45, lB=.45, dx=.5),
                       K(4, **PUNCH_B), K(8, **PUNCH_B), K(16)]),
    'jab3': dict(jp='弱攻撃③(キック)', len=30,
                 hits=[H(5, 8, 8, 6, 5, 4, 361, 30, 25)],
                 keys=[K(0), K(3, lean=-.1, lB=-.5, lF=.3, kF=-.9, aF=-.3, aB=.9, eB=1.0, dx=-1.0),
                       K(6, **KICK_J3), K(11, **KICK_J3), K(22), K(29)]),
    'ftilt': dict(jp='横強(キック)', len=30,
                  hits=[H(6, 9, 8.5, 7, 4.8, 5, 361, 12, 100)],
                  keys=[K(0), K(4, lean=-.1, lF=-.5, kF=-1.2, lB=0.0, aF=.9, aB=-.7, dx=-1.0),
                        K(7, **KICK_FT), K(12, **KICK_FT), K(22, lean=0.0, lF=.5, kF=-.5), K(29)]),
    'utilt': dict(jp='上強(ヘッドバット)', len=34,
                  hits=[H(5, 8, 7, 12, 5, 5, 100, 20, 90, grp=0),
                        H(9, 13, 1, 19, 5.5, 5, 100, 20, 90, grp=0)],
                  keys=[K(0), K(4, lean=.55, head=.5, dy=-1.5, aF=.8, aB=.2, lF=.6, kF=-.8, lB=-.5, kB=-.4),
                        K(7, lean=.15, head=-.4, aF=2.3, aB=2.0, eF=.3, eB=.3, dy=0.3),
                        K(11, lean=-.45, head=-.7, aF=2.8, aB=2.6, eF=.2, eB=.2, lF=.1, lB=-.1, kF=-.1, kB=-.1, dy=.5),
                        K(24, lean=-.2, head=-.3, aF=1.2, aB=1.0), K(33)]),
    'dtilt': dict(jp='下強(足払い)', len=26,
                  hits=[H(5, 8, 9, 2.5, 4.5, 5, 80, 35, 35)],
                  keys=[K(0), K(3, dy=-3.0, lean=.45, lF=.9, kF=-1.6, lB=1.0, kB=-2.0, aF=.9, aB=.5, eF=1.2, eB=1.2),
                        K(5, dy=-3.0, lean=.5, lF=1.25, kF=0.0, lB=1.0, kB=-2.1, aF=.9, aB=.5, eF=1.2, eB=1.2, dx=1.0),
                        K(9, dy=-3.0, lean=.5, lF=1.25, kF=0.0, lB=1.0, kB=-2.1, aF=.9, aB=.5, eF=1.2, eB=1.2, dx=1.0),
                        K(20, **CROUCH), K(25)]),
    'fireball': dict(jp='必殺技N ファイアボール', len=38, hits=[], hook=hk_fireball,
                     keys=[K(0), K(5, lean=-.1, aF=-.8, aB=-.8, eF=.8, eB=.8),
                           K(12, lean=.25, aF=1.45, aB=1.45, eF=.1, eB=.1, dx=1.5, lF=.5, kF=-.4, lB=-.5, kB=-.1),
                           K(18, lean=.25, aF=1.45, aB=1.45, eF=.1, eB=.1, dx=1.5, lF=.5, kF=-.4, lB=-.5, kB=-.1),
                           K(30), K(37)]),
    'cape': dict(jp='必殺技 横B マント', len=38,
                 hits=[H(5, 10, 8, 10, 6.5, 5, 361, 10, 60, turn=True)], hook=hk_cape,
                 keys=[K(0), K(4, spin=-0.4, lean=-.1, aF=-.9, eF=.5, aB=1.0, eB=1.2),
                       K(8, spin=0.5, lean=.2, aF=1.8, eF=0.0, aB=.8, eB=.6),
                       K(14, spin=0.5, lean=.2, aF=1.8, eF=0.0, aB=.8, eB=.6),
                       K(24), K(37)]),
    'upb': dict(jp='必殺技 上B スーパージャンプパンチ', len=44, hook=hk_upb,
                hits=[H(3, 5, 4, 12, 6, 4, 85, 20, 20, grp=0),
                      H(6, 19, 3, 13, 6, 1, 90, 10, 0, grp=1, rehit=3, carry=True),
                      H(20, 24, 3, 20, 7, 3, 80, 45, 105, grp=2)],
                keys=[K(0), K(2, **CROUCH),
                      K(4, dy=0.0, lean=-.05, aF=3.0, eF=.2, aB=.5, eB=1.2, lF=.6, kF=-.6, lB=-.2, kB=-.8, spin=0.0),
                      K(22, dy=0.0, lean=-.05, aF=3.0, eF=.2, aB=.5, eB=1.2, lF=.6, kF=-.6, lB=-.2, kB=-.8, spin=TAU),
                      K(30, aF=2.6, eF=.3, aB=1.0, lF=.3, kF=-.4, lB=-.3, kB=-.4, spin=TAU),
                      K(43, spin=TAU)]),
    'fludd': dict(jp='必殺技 下B ポンプ(F.L.U.D.D.)', len=52, hits=[], hook=hk_fludd,
                  keys=[K(0), K(6, lean=.1, aF=1.4, aB=1.4, eF=.2, eB=.2, lF=.5, kF=-.3, lB=-.5, kB=-.1, dx=-.5),
                        K(42, lean=.1, aF=1.4, aB=1.4, eF=.2, eB=.2, lF=.5, kF=-.3, lB=-.5, kB=-.1, dx=-.5),
                        K(51)]),
    'nair': dict(jp='空中N(回転キック)', len=32,
                 hits=[H(4, 14, 6, 9, 6.5, 6, 361, 18, 100)],
                 keys=[K(0), K(3, lean=.1, lF=.5, lB=-.5, aF=.8, aB=-.8),
                       K(5, lean=0.0, lF=1.5, kF=0.0, lB=-1.5, kB=0.0, aF=1.2, aB=-1.2, eF=.2, eB=.2),
                       K(14, lean=0.0, lF=1.5, kF=0.0, lB=-1.5, kB=0.0, aF=1.2, aB=-1.2, eF=.2, eB=.2),
                       K(20), K(31)]),

    'uair': dict(jp='空上(上方向キック)', len=28,
                 hits=[H(5, 9, 1, 19, 5.8, 7, 85, 18, 105)],
                 keys=[K(0), K(3, lean=-.2, aF=1.0, aB=1.0, lF=-.6, lB=.6),
                       K(6, lean=-.5, aF=2.8, aB=2.5, lF=-1.2, lB=1.2, kF=-.2, kB=-.2),
                       K(11, lean=-.3, aF=2.2, aB=2.0), K(20), K(27)]),
    'dair': dict(jp='空下(下方向踏み)', len=32,
                 hits=[H(7, 12, 5, -2, 5.5, 8, 270, 16, 95)],
                 keys=[K(0), K(3, lean=.2, lF=1.0, lB=-1.0, aF=.8, aB=.8),
                       K(7, lean=.5, lF=2.8, lB=2.8, kF=0, kB=0, aF=-.3, aB=-.3),
                       K(12, lean=.3, lF=2.5, lB=2.5), K(21), K(31)]),
    'fair': dict(jp='空前(前方パンチ)', len=29,
                 hits=[H(6, 9, 9, 10, 5.2, 7, 361, 16, 100)],
                 keys=[K(0), K(3, lean=.2, aF=-.8, eF=.8, lF=.5, lB=-.5),
                       K(6, **PUNCH_F), K(10, **PUNCH_F), K(20), K(28)]),
    'bair': dict(jp='空後(後方キック)', len=31,
                 hits=[H(6, 10, 8, 9, 5.5, 9, 361, 18, 110)],
                 keys=[K(0), K(3, lean=-.25, aB=1.0, eB=.3, lB=-1.0, kB=-.2),
                       K(7, **PUNCH_B), K(11, **PUNCH_B), K(22), K(30)]),
    'grab': dict(jp='つかみ', len=25,
                 hits=[H(6, 9, 9, 9, 5.0, 0, 361, 0, 0, grab=True)],
                 keys=[K(0), K(3, lean=.25, aF=1.5, eF=.2, aB=-.5),
                       K(6, lean=.15, aF=2.5, eF=.0, aB=-.3, eB=.8),
                       K(10, lean=.1, aF=2.1, eF=.2), K(18), K(24)]),

}

MARIO = dict(hat=(0.85, 0.10, 0.10), shirt=(0.85, 0.10, 0.10), pants=(0.15, 0.25, 0.80),
             skin=(0.98, 0.78, 0.60), hair=(0.35, 0.20, 0.08), glove=(0.97, 0.97, 0.97),
             shoe=(0.40, 0.22, 0.08), eye=(0.10, 0.10, 0.35))
LUIGI = dict(MARIO, hat=(0.10, 0.62, 0.20), shirt=(0.10, 0.62, 0.20), pants=(0.20, 0.20, 0.65))
PEACH = dict(MARIO, hat=(0.98, 0.35, 0.62), shirt=(0.98, 0.35, 0.62), pants=(0.75, 0.25, 0.50),
             hair=(0.95, 0.62, 0.18), shoe=(0.85, 0.18, 0.38))
BOWSER = dict(MARIO, hat=(0.90, 0.55, 0.08), shirt=(0.12, 0.62, 0.20), pants=(0.22, 0.18, 0.16),
              skin=(0.92, 0.80, 0.42), hair=(0.85, 0.18, 0.08), shoe=(0.25, 0.18, 0.12))
LINK = dict(MARIO, hat=(0.20, 0.68, 0.24), shirt=(0.20, 0.68, 0.24), pants=(0.35, 0.32, 0.20),
            hair=(0.85, 0.72, 0.40), shoe=(0.32, 0.22, 0.12))
KIRBY = dict(MARIO, hat=(0.95, 0.42, 0.68), shirt=(0.95, 0.42, 0.68), pants=(0.95, 0.42, 0.68),
             skin=(1.0, 0.65, 0.78), hair=(0.95, 0.42, 0.68), shoe=(0.75, 0.12, 0.30))
SAMUS = dict(MARIO, hat=(0.95, 0.40, 0.08), shirt=(0.95, 0.40, 0.08), pants=(0.82, 0.25, 0.06),
             skin=(0.95, 0.68, 0.42), hair=(0.12, 0.20, 0.55), glove=(0.95, 0.68, 0.12))
FOX = dict(MARIO, hat=(0.85, 0.42, 0.16), shirt=(0.78, 0.35, 0.12), pants=(0.32, 0.34, 0.40),
           skin=(0.95, 0.63, 0.38), hair=(0.82, 0.38, 0.12), shoe=(0.75, 0.75, 0.80))
ROSTER = [
    {'name':'マリオ', 'en':'MARIO', 'pal':MARIO, 'weight':98, 'speed':1.00},
    {'name':'ルイージ', 'en':'LUIGI', 'pal':LUIGI, 'weight':94, 'speed':1.07},
    {'name':'ピーチ', 'en':'PEACH', 'pal':PEACH, 'weight':88, 'speed':0.96},
    {'name':'クッパ', 'en':'BOWSER', 'pal':BOWSER, 'weight':125, 'speed':0.78},
    {'name':'リンク', 'en':'LINK', 'pal':LINK, 'weight':100, 'speed':0.94},
    {'name':'カービィ', 'en':'KIRBY', 'pal':KIRBY, 'weight':78, 'speed':1.02},
    {'name':'サムス', 'en':'SAMUS', 'pal':SAMUS, 'weight':108, 'speed':0.91},
    {'name':'フォックス', 'en':'FOX', 'pal':FOX, 'weight':82, 'speed':1.13},
]



MOVE_EN = {'jab1': 'Jab 1', 'jab2': 'Jab 2', 'jab3': 'Jab 3 (kick)', 'ftilt': 'Forward Tilt',
           'utilt': 'Up Tilt', 'dtilt': 'Down Tilt', 'fireball': 'Neutral B: Fireball',
           'cape': 'Side B: Cape', 'upb': 'Up B: Super Jump Punch', 'fludd': 'Down B: F.L.U.D.D.',
           'nair': 'Neutral Air', 'uair': 'Up Air', 'dair': 'Down Air', 'fair': 'Forward Air', 'bair': 'Back Air', 'grab': 'Grab'}


def find_jp_font():
    if FORCE_ENGLISH:
        return None
    # PythonIDE内に置かれたフォントファイルを最優先で読み込む。
    # 作業フォルダと、この.pyファイルと同じフォルダの両方を確認する。
    for base in (os.getcwd(), os.path.dirname(os.path.abspath(__file__))):
        candidate = os.path.join(base, 'NotoSansJP-Regular.ttf')
        if os.path.isfile(candidate):
            return candidate
    # フォントファイルが見つからない場合だけ、端末内の日本語フォントを探す。
    for n in ('hiraginosans', 'hiraginokakugothicpron', 'hiraginomarugothicpron', 'notosansjp',
              'notosanscjkjp', 'applesdgothicneo', 'arialunicodems', 'meiryo', 'msgothic'):
        try:
            font_path = pygame.font.match_font(n)
        except Exception:
            font_path = None
        if font_path:
            return font_path
    return None


class Inp:
    __slots__ = ('x', 'y', 'jump', 'jump_held', 'a', 'b', 'shield', 'grab')

    def __init__(self):
        self.x = 0.0; self.y = 0.0
        self.jump = False; self.jump_held = False; self.a = False; self.b = False
        self.shield = False; self.grab = False


# ====================================================================
#  ファイター
# ====================================================================
class Fighter:
    W = 98          # マリオの体重

    def __init__(self, idx, name, pal, sx, face, weight=98, speed=1.0, char_id=0):
        self.idx = idx; self.name = name; self.pal = pal
        self.W = weight; self.speed_scale = speed; self.char_id = char_id
        self.sx = sx; self.f0 = face
        self.stocks = 3
        self.last_move = ['', 0]
        self.ai_cd = 40
        self.respawn(True)

    def respawn(self, first):
        self.x = self.sx if first else 0.0
        self.y = 0.0 if first else 62.0
        self.px = self.x; self.py = self.y
        self.vx = self.vy = self.kbx = self.kby = 0.0
        self.pct = 0.0; self.shield_hp = 50.0
        self.face = self.f0 if first else (1 if self.sx < 0 else -1)
        self.yaw = -0.5 if self.face > 0 else math.pi + 0.5
        self.state = 'idle' if first else 'air'
        self.grounded = first
        self.inv = 0 if first else 210
        self.plat = 0 if first else 150
        self.helpless = False; self.jumps = 1; self.rising = False; self.fastfall = False
        self.atk = None; self.af = 0; self.chain = False; self.hit_log = {}
        self.hitlag = 0; self.stun = 0; self.tumble = False; self.tumble_dir = 1
        self.flip = 0.0; self.carry = None; self.carried_by = None
        self.lag = 0; self.shake = 0; self.t = 0; self.phase = 0.0; self.gscale = 1.0
        if self.state != 'shield':
            self.shield_hp = min(50.0, self.shield_hp + 0.08)
        self.air_t = 0; self.ko_timer = 0; self.inp = Inp()
        self.ledge_side = 0; self.ledge_lock = 0
        self.ledge_grabs = 0          # 地面に戻るまでの連続崖つかまり回数
        self.ledge_inv_delay = 0      # つかまり直後の2フレーム猶予
        self.ledge_inv_eligible = False
        self.pose = None
        self.pose_update()

    # ---- 当たり判定 ----
    def hurt_overlap(self, x, y, r):
        
        if self.state == 'ledge':
            # 崖つかまり中は、頭や胴体の当たり判定を低めにする
            cs = ((3.0, 3.0), (8.0, 3.4), (13.0, 3.5))
        elif self.state == 'crouch':
            cs = ((4.0, 4.8), (8.5, 4.8), (12.0, 3.8))
        else:
            cs = ((5.0, 4.6), (11.0, 5.0), (15.5, 4.2))

        for cy, cr in cs:
            dx = x - self.x
            dy = y - (self.y + cy)
            rr = r + cr
            if dx * dx + dy * dy < rr * rr:
                return True
        return False

    # ---- 毎フレーム ----
    def tick(self, inp, game):
        self.inp = inp
        self.t += 1
        if self.last_move[1] > 0:
            self.last_move[1] -= 1
        if self.state == 'dead':
            self.ko_timer -= 1
            if self.ko_timer <= 0 and self.stocks > 0:
                self.respawn(False)
            return
        if self.inv > 0:
            self.inv -= 1
        if self.state == 'ledge' and self.ledge_inv_delay > 0:
            self.ledge_inv_delay -= 1
            if self.ledge_inv_delay == 0 and self.ledge_inv_eligible:
                # Ultimate風：つかまり始めの2フレームは無敵にならず、その後に短い無敵。
                self.inv = max(self.inv, 45)
                self.ledge_inv_eligible = False
        if self.shake > 0:
            self.shake -= 1
        if self.hitlag > 0:
            self.hitlag -= 1
            return
        self.gscale = 1.0
        if self.state != 'shield':
            self.shield_hp = min(50.0, self.shield_hp + 0.08)
        if self.plat > 0:
            self.plat -= 1
            if inp.jump or inp.a or inp.b or abs(inp.x) > 0.6 or self.plat == 0:
                self.plat = 0
                self.state = 'air'
            else:
                self.vx = self.vy = 0.0
                self.state = 'idle'
                self.pose_update()
                return
        if self.stun > 0:
            self.stun -= 1
            if self.stun == 0:
                self.tumble = False
                self.carried_by = None
                self.state = 'idle' if self.grounded else 'air'
        elif self.state == 'attack':
            self.run_attack(inp, game)
        elif self.state == 'ledge':
            # 崖をつかんだ直後は約0.5秒、入力を受け付けずにつかまりモーションを維持。
            self.vx = self.vy = self.kbx = self.kby = 0.0
            self.grounded = False
            if self.ledge_lock > 0:
                self.ledge_lock -= 1
            else:
                side = self.ledge_side or sgn(self.x)
                if inp.jump:
                    # 崖ジャンプ：ステージ内側へ戻る。
                    self.x = side * (STAGE_HW - 4.0)
                    self.y = -4.0
                    self.vx = -side * 1.0
                    self.vy = JUMP_V * 0.9
                    self.state = 'air'
                    self.jumps = 1
                    self.air_t = 0
                    self.rising = True
                    self.grounded = False
                elif abs(inp.x) > 0.7 and inp.x * side > 0:
                    # 外向きに倒すと崖から手を離す。
                    self.x = side * (STAGE_HW + 2.0)
                    self.y = -11.0
                    self.vx = side * 0.6
                    self.vy = -0.25
                    self.state = 'air'
                    self.air_t = 0
                    self.grounded = False
        elif self.state == 'shield':
            if not inp.shield:
                self.state = 'idle' if self.grounded else 'air'
            else:
                self.vx = approach(self.vx, 0.0, 0.25)
        elif self.state == 'landing':
            self.lag -= 1
            if self.lag <= 0:
                self.state = 'idle'
        else:
            self.control(inp, game)
        self.physics(game)
        self.pose_update()

    # ---- 操作 ----
    def control(self, inp, game):
        sx, sy = inp.x, inp.y
        if self.grounded:
            if self.state == 'air':
                self.state = 'idle'
            self.jumps = 1; self.helpless = False; self.fastfall = False
            if inp.shield:
                self.state = 'shield'; self.vx = approach(self.vx, 0.0, 0.2); return
            if inp.grab:
                self.start_attack('grab'); return
            if inp.a:
                self.start_attack(self.pick_ground(inp)); return
            if inp.b:
                self.start_special(inp); return
            if inp.jump:
                self.vy = JUMP_V; self.grounded = False; self.state = 'air'
                self.rising = True
                game.puff(self.x, self.y)
                return
            if sy < -0.6 and abs(sx) < 0.5:
                self.state = 'crouch'; tv = 0.0
            elif abs(sx) > 0.25:
                self.face = 1 if sx > 0 else -1
                if abs(sx) > 0.75:
                    self.state = 'run'; tv = self.face*RUN_V*self.speed_scale
                else:
                    self.state = 'walk'; tv = self.face*WALK_V*self.speed_scale*(abs(sx)/0.75)
            else:
                self.state = 'idle'; tv = 0.0
            self.vx = approach(self.vx, tv, 0.24 if tv != 0 else 0.2)
        else:
            self.state = 'air'
            if inp.jump and self.jumps > 0 and not self.helpless:
                self.jumps -= 1
                self.vy = DJUMP_V
                if abs(sx) > 0.3:
                    self.vx = sx*0.95
                else:
                    self.vx *= 0.3
                self.rising = False; self.fastfall = False
                game.puff(self.x, self.y + 6)
                return
            if not self.helpless:
                if inp.a:
                    if inp.y > 0.55:
                        self.start_attack('uair')
                    elif inp.y < -0.55:
                        self.start_attack('dair')
                    elif abs(inp.x) > 0.45:
                        self.start_attack('fair' if inp.x*self.face > 0 else 'bair')
                    else:
                        self.start_attack('nair')
                    return
                if inp.shield:
                    self.state = 'shield'; self.vx = approach(self.vx, 0.0, 0.2); return
                if inp.grab:
                    self.start_attack('grab'); return
                if inp.b:
                    self.start_special(inp); return
            if self.rising:
                if not inp.jump_held and self.vy > 1.2:
                    self.vy *= 0.5; self.rising = False
                if self.vy <= 0:
                    self.rising = False
            if abs(sx) > 0.2:
                self.vx = approach(self.vx, sx*AIR_MAX*self.speed_scale, 0.045)
                if abs(sx) > 0.5:
                    self.face = 1 if sx > 0 else -1
            else:
                self.vx = approach(self.vx, 0.0, 0.01)
            if sy < -0.7 and self.vy <= 0:
                self.fastfall = True

    def pick_ground(self, inp):
        sx, sy = inp.x, inp.y
        if sy > 0.55 and abs(sy) >= abs(sx):
            return 'utilt'
        if sy < -0.55 and abs(sy) > abs(sx):
            return 'dtilt'
        if abs(sx) > 0.4:
            self.face = sgn(sx)
            return 'ftilt'
        return 'jab1'

    def start_special(self, inp):
        sx, sy = inp.x, inp.y
        if sy > 0.55 and abs(sy) >= abs(sx):
            self.start_attack('upb')
        elif sy < -0.55 and abs(sy) > abs(sx):
            self.start_attack('fludd')
        elif abs(sx) > 0.4:
            self.face = sgn(sx)
            self.start_attack('cape')
        else:
            self.start_attack('fireball')

    def start_attack(self, name):
        self.state = 'attack'; self.atk = name; self.af = 0
        self.chain = False; self.hit_log = {}; self.carry = None
        self.last_move = [name, 80]

    def run_attack(self, inp, game):
        A = ATTACKS[self.atk]
        self.af += 1
        ch = A.get('chain')
        if ch and inp.a and ch[0] <= self.af <= ch[1]:
            self.chain = True
        hk = A.get('hook')
        if hk:
            hk(self, self.af, game)
        if ch and self.chain and self.af >= ch[2]:
            self.start_attack(A['next']); return
        if self.af >= A['len']:
            self.end_attack()

    def end_attack(self):
        was = self.atk
        self.atk = None; self.carry = None
        if self.grounded:
            self.state = 'idle'
        else:
            self.state = 'air'
            if was == 'upb':
                self.helpless = True

    # ---- 物理 ----
    def physics(self, game):
        self.px = self.x; self.py = self.y
        if self.state == 'ledge':
            # 崖つかまり中は重力・ノックバック・通常の衝突処理を停止。
            self.vx = self.vy = self.kbx = self.kby = 0.0
            return
        if not self.grounded:
            self.vy -= GRAV*self.gscale
            lim = FAST_FALL if self.fastfall else FALL_MAX
            if self.vy < -lim:
                self.vy = -lim
            self.air_t += 1
        else:
            self.air_t = 0
            if self.state in ('attack', 'landing', 'hit'):
                self.vx = approach(self.vx, 0.0, 0.18)
            self.kbx = approach(self.kbx, 0.0, 0.1)
        self.x += self.vx + self.kbx
        self.y += self.vy + self.kby
        m = math.hypot(self.kbx, self.kby)
        if m > 0:
            nm = m - KB_DECAY
            if nm < 0:
                nm = 0.0
            s = nm / m
            self.kbx *= s; self.kby *= s
        self.collide(game)

    def collide(self, game):
        was = self.grounded
        self.grounded = False
        hw = CHAR_HW
        s1 = STAGE_HW; by = -BODY_T
        if self.x + hw > -s1 and self.x - hw < s1 and self.y < 0.02 and self.y + CHAR_H > by:
            if self.py >= -0.05:                       # 上から着地
                self.y = 0.0
                if self.vy < 0: self.vy = 0.0
                if self.kby < 0: self.kby = 0.0
                self.grounded = True
            elif self.py + CHAR_H <= by + 0.05:        # 下からぶつかる
                self.y = by - CHAR_H
                if self.vy > 0: self.vy = 0.0
                if self.kby > 0: self.kby = -self.kby*0.3
            else:                                      # 横から
                self.x = (-s1 - hw) if self.px < 0 else (s1 + hw)
                self.vx = 0.0; self.kbx = 0.0
        # 小戦場風のすり抜け床。上から降りてきた時だけ着地できる。
        # 床の上にいる間も、毎フレーム足元を維持する。
        for px, py, phw, pd in PLATFORMS:
            if (abs(self.x - px) <= phw + hw and
                    self.py >= py - 0.15 and self.y <= py + 0.15 and
                    self.vy + self.kby <= 0.15):
                self.y = py
                if self.vy < 0: self.vy = 0.0
                if self.kby < 0: self.kby = 0.0
                self.grounded = True
                break

        # 崖つかまり(スマブラUltimateの挙動を参考にしたスナップ判定)
        # ・キャラの中心ではなく、崖に届く範囲にいるかを判定
        # ・ステージ上面より下、下降中のみ通常の崖つかまりが可能
        # ・向きは条件にしないので、崖と反対を向いていてもつかめる
        # ・連続つかまりは最大6回。着地または吹っ飛びを受けると回数リセット
        
        side = 1 if self.x >= 0 else -1
        edge_dx = abs(abs(self.x) - s1)

        # 崖の近くまで来たら、少し離れていてもつかめるようにする
        near_edge = edge_dx <= (CHAR_HW + 4.0)

        # 崖の下から手が届く範囲を広げる
        # ステージ上面より上(y >= 0)ではつかまない
        in_ledge_height = (-CHAR_H - 8.0) <= self.y <= -1.0

        falling = (self.vy + self.kby) <= 0.05
        eligible_state = self.state in ('air', 'hit')
        can_regrab = self.ledge_grabs < 6
        if (not self.grounded and eligible_state and self.air_t > 2 and
                near_edge and in_ledge_height and falling and can_regrab):
            self.ledge_side = side
            # 崖の外側に一定距離で固定。キャラの向きに関係なく同じ位置へスナップ。
            self.x = side * (s1 + 1.5)
            self.y = -16.5
            self.vx = self.vy = self.kbx = self.kby = 0.0
            self.grounded = False
            self.helpless = False
            self.state = 'ledge'
            self.ledge_lock = 30  # 以前の要望どおり、操作不能は約0.5秒
            self.ledge_grabs += 1
            self.ledge_inv_delay = 2
            self.ledge_inv_eligible = (self.ledge_grabs == 1)
            # 再つかまりでは新たな無敵を付けない(Ultimate風)。
            if not self.ledge_inv_eligible:
                self.inv = 0
            self.face = -side
            game.puff(side * s1, 1.5)
        if self.grounded and not was:
            self.on_land(game)

    def on_land(self, game):
        self.ledge_grabs = 0
        self.ledge_inv_delay = 0; self.ledge_inv_eligible = False
        self.fastfall = False; self.rising = False; self.jumps = 1
        game.puff(self.x, 0.5)
        if self.state == 'attack':
            self.atk = None; self.carry = None
            self.state = 'landing'; self.lag = 7
        elif self.state == 'air':
            if self.helpless:
                self.state = 'landing'; self.lag = 14; self.helpless = False
            else:
                self.state = 'idle'

    # ---- ポーズ ----
    def target_pose(self):
        st = self.state
        if st == 'attack':
            return interp(ATTACKS[self.atk]['keys'], self.af)
        p = dict(DEF)
        
        if st == 'ledge':
            # 崖につかまり、頭と胴体を崖の下へ引き込むポーズ
            p.update(
                aF=-2.9, aB=2.9,
                eF=-0.65, eB=0.65,
                lF=0.25, lB=-0.25,
                kF=-0.25, kB=-0.25,
                lean=0.0, dy=-1.5, head=0.0
            )
        elif st == 'hit':
            if self.tumble:
                p.update(lean=-.2, aF=2.6, aB=2.2, eF=.3, eB=.3, lF=.9, lB=.4, kF=-1.0, kB=-.6)
            else:
                p.update(lean=-.45, head=-.5, aF=1.9, aB=1.2, eF=.4, eB=.4, lF=.5, lB=-.5,
                         kF=-.3, kB=-.5, dx=-1.0)
        elif st in ('walk', 'run'):
            self.phase += abs(self.vx)*0.3
            s = math.sin(self.phase); c = math.cos(self.phase)
            amp = 0.7 if st == 'walk' else 1.05
            p.update(lF=s*amp, lB=-s*amp,
                     kF=-0.15 - 0.9*max(0.0, c), kB=-0.15 - 0.9*max(0.0, -c),
                     aF=-s*amp*0.9, aB=s*amp*0.9,
                     eF=0.9 if st == 'walk' else 1.4, eB=0.9 if st == 'walk' else 1.4,
                     lean=0.08 if st == 'walk' else 0.35, dy=-0.2 - abs(c)*0.35)
        elif st == 'crouch':
            p.update(CROUCH)
        elif st == 'shield':
            p.update(lean=-.18, aF=1.8, aB=-1.8, eF=.2, eB=.2, lF=.25, lB=-.25, kF=-.35, kB=-.35, dy=-1.0)
        elif st == 'landing':
            p.update(dy=-1.8, lean=.25, lF=.7, kF=-1.3, lB=.7, kB=-1.3, aF=.7, aB=.5)
        elif not self.grounded:
            if self.helpless:
                p.update(aF=2.2, aB=2.5, eF=.2, eB=.2, lF=.5, lB=-.5, kF=-.4, kB=-.4)
            elif self.vy > 0.3:
                p.update(aF=3.0, aB=-.3, eF=.3, eB=.6, lF=.9, kF=-1.2, lB=-.3, kB=-.6, lean=0.0)
            else:
                p.update(aF=2.1, aB=1.7, eF=.4, eB=.4, lF=.35, lB=-.35, kF=-.2, kB=-.2)
        else:
            p['dy'] = -0.2 + math.sin(self.t*0.08)*0.12
        return p

    def pose_update(self):
        tg = self.target_pose()
        cur = self.pose
        if cur is None:
            self.pose = dict(tg)
        else:
            for k, v in tg.items():
                if k == 'spin':
                    cur[k] = v
                else:
                    cur[k] += (v - cur[k])*0.55
        targ = -0.5 if self.face > 0 else math.pi + 0.5
        d = (targ - self.yaw + math.pi) % TAU - math.pi
        self.yaw += d*0.35
        if self.stun > 0 and self.tumble:
            self.flip += self.tumble_dir*0.42
        else:
            self.flip = 0.0


# ====================================================================
#  CPU
# ====================================================================
def ai_input(f, o, g):
    i = Inp()
    i.jump_held = True
    if f.state == 'dead' or f.plat > 0 or f.state in ('hit', 'landing'):
        return i
    f.ai_cd = max(0, f.ai_cd - 1)
    dx = o.x - f.x; dy = o.y - f.y; ad = abs(dx); tw = sgn(dx)
    if f.state == 'attack':
        if f.atk and f.atk.startswith('jab') and ad < 18 and random.random() < 0.3:
            i.a = True
        return i
    danger = (not f.grounded) and (abs(f.x) > STAGE_HW + 1 or f.y < -4)
    if danger:
        under = f.y < -2 and abs(f.x) < STAGE_HW + 6
        i.x = sgn(f.x) if under else -sgn(f.x)
        if f.helpless:
            return i
        if f.jumps > 0 and f.vy < 0.3 and f.y < 16 and not under:
            i.jump = True
        elif f.jumps == 0 and f.y < 2 and not under and abs(f.x) < STAGE_HW + 42:
            i.y = 1.0; i.b = True; i.x = -sgn(f.x)*0.9
        return i
    if f.grounded:
        want = 0.0
        if ad > 16:
            want = tw
        if want != 0 and abs(f.x + tw*8) > STAGE_HW - 2:
            want = 0.0
        if abs(o.x) > STAGE_HW + 6 or o.y < -8:
            want = 0.0 if abs(f.x) > STAGE_HW - 14 else tw
        i.x = want*(1.0 if ad > 45 else 0.55)
        if f.ai_cd == 0:
            if ad < 17 and abs(dy) < 14:
                f.face = tw
                r = random.random()
                if dy > 12:
                    i.y = 1.0; i.a = True
                elif r < 0.30:
                    i.a = True; i.x = 0.0
                elif r < 0.55:
                    i.a = True; i.x = tw*0.6
                elif r < 0.70:
                    i.a = True; i.y = -1.0; i.x = 0.0
                elif r < 0.80:
                    i.b = True; i.x = tw*0.6
                else:
                    i.b = True; i.y = -1.0; i.x = 0.0
                f.ai_cd = random.randint(16, 36)
            elif ad > 38 and abs(dy) < 20 and abs(f.x) < STAGE_HW - 10 and random.random() < 0.04:
                f.face = tw
                i.b = True; i.x = 0.0
                f.ai_cd = 40
            elif dy > 18 and ad < 14 and random.random() < 0.03:
                i.b = True; i.y = 1.0; i.x = 0.0
                f.ai_cd = 50
        if dy > 18 and ad < 24 and random.random() < 0.03:
            i.jump = True
    else:
        if abs(f.x) > STAGE_HW - 6:
            i.x = -sgn(f.x)*0.8
        elif ad > 10:
            i.x = tw*0.7
        if ad < 14 and abs(dy) < 12 and random.random() < 0.08 and f.ai_cd == 0:
            i.a = True; f.ai_cd = 24
    return i


# ====================================================================
#  ゲーム本体
# ====================================================================

class Game:
    def __init__(self, screen):
        self.screen = screen
        self.W, self.H = screen.get_size()
        self.cam = Cam()
        self.tmap = {}
        self.svec = (0.0, 0.0)
        self.sbase = None
        self.sknob = None
        self.jump_held = False
        self.edge = {'a': False, 'b': False, 'jump': False, 'grab': False}
        self.btn_down = set()
        self.keys = set()
        self.seen_finger = False
        self.acc = 0.0
        self.frame_no = 0
        rnd = random.Random(7)
        self.stars = [(rnd.random(), rnd.random(), rnd.random()) for _ in range(90)]
        self.mode = 'title'
        self.p1_choice = 0
        self.cpu_choice = 1
        self.select_side = 0  # 0=プレイヤー、1=CPU
        self.winner = None
        self.over_t = 0
        self.jp_font = find_jp_font()
        self.fonts = {}
        self.new_match()

    # ---------- マッチ ----------
    def new_match(self):
        c1 = ROSTER[self.p1_choice]
        c2 = ROSTER[self.cpu_choice]
        self.p1 = Fighter(0, c1['name'], c1['pal'], -22.0, 1, c1['weight'], c1['speed'], self.p1_choice)
        self.p2 = Fighter(1, c2['name'] + ' CPU', c2['pal'], 22.0, -1, c2['weight'], c2['speed'], self.cpu_choice)
        self.fs = [self.p1, self.p2]
        self.fireballs = []
        self.fx = []
        self.shake = 0
        self.winner = None
        self.over_t = 0
        self.cam.tx = 0.0; self.cam.ty = 14.0; self.cam.dist = 205.0

    def start(self):
        self.new_match()
        self.mode = 'play'
        self.tmap = {}
        self.svec = (0.0, 0.0); self.sbase = None; self.sknob = None
        self.jump_held = False
        for k in self.edge:
            self.edge[k] = False
        self.btn_down = set()

    def begin_select(self):
        self.mode = 'select'
        self.tmap = {}
        self.svec = (0.0, 0.0); self.sbase = None; self.sknob = None

    def select_touch(self, x, y):
        W, H = self.W, self.H
        # 選択対象タブ
        tab_y = int(H*0.19)
        if tab_y-32 <= y <= tab_y+32:
            if x < W*0.5:
                self.select_side = 0
            else:
                self.select_side = 1
            return
        # 4列 x 2行のキャラクターカード
        cols, rows = 4, 2
        margin = max(16, int(W*0.035))
        gap = max(10, int(W*0.014))
        card_w = (W - margin*2 - gap*(cols-1)) / cols
        card_h = min(H*0.19, 118)
        start_y = H*0.29
        for idx, ch in enumerate(ROSTER):
            col, row = idx % cols, idx // cols
            x0 = margin + col*(card_w+gap)
            y0 = start_y + row*(card_h+gap)
            if x0 <= x <= x0+card_w and y0 <= y <= y0+card_h:
                if self.select_side == 0:
                    self.p1_choice = idx
                else:
                    self.cpu_choice = idx
                return
        # START ボタン
        if y > H*0.80:
            self.start()

    def other(self, f):
        return self.p2 if f is self.p1 else self.p1

    # ---------- 入力 ----------
    def L(self, jp, en):
        return jp if self.jp_font else en

    def btns(self, W, H):
        return {'A': (W - 115, H - 125, 58),
                'B': (W - 235, H - 82, 46),
                'J': (W - 225, H - 195, 46),
                'S': (W - 355, H - 125, 45),
                'G': (W - 340, H - 220, 43)}

    def press(self, name):
        self.btn_down.add(name)
        if name == 'A':
            self.edge['a'] = True
        elif name == 'B':
            self.edge['b'] = True
        elif name == 'J':
            self.edge['jump'] = True
            self.jump_held = True
        elif name == 'G':
            self.edge['grab'] = True

    def release(self, name):
        self.btn_down.discard(name)
        if name == 'J':
            self.jump_held = False

    def set_stick(self, x, y):
        bx, by = self.sbase
        R = 62.0
        dx = x - bx; dy = y - by
        d = math.hypot(dx, dy)
        if d > R*1.6:
            k = (d - R*1.6)/d
            self.sbase = (bx + dx*k, by + dy*k)
            bx, by = self.sbase
            dx = x - bx; dy = y - by
            d = math.hypot(dx, dy)
        vx = dx/R; vy = -dy/R
        m = math.hypot(vx, vy)
        if m > 1.0:
            vx /= m; vy /= m
        if m < 0.18:
            vx = vy = 0.0
        self.svec = (vx, vy)
        k = min(1.0, d/R) if d > 0 else 0
        self.sknob = (bx + (dx/d*R*k if d > 0 else 0), by + (dy/d*R*k if d > 0 else 0))

    def touch_down(self, tid, x, y):
        W, H = self.W, self.H
        if self.mode == 'title':
            self.begin_select(); return
        if self.mode == 'select':
            self.select_touch(x, y); return
        if self.mode == 'over':
            if self.over_t > 60:
                self.begin_select()
            return
        if x > W - 120 and y < 70:
            self.start(); return
        for name, (bx, by, br) in self.btns(W, H).items():
            if (x-bx)**2 + (y-by)**2 <= (br + 22)**2:
                self.tmap[tid] = name
                self.press(name)
                return
        if x < W*0.55:
            self.tmap[tid] = 'stick'
            self.sbase = (x, y)
            self.set_stick(x, y)

    def touch_move(self, tid, x, y):
        if self.tmap.get(tid) == 'stick' and self.sbase:
            self.set_stick(x, y)

    def touch_up(self, tid):
        r = self.tmap.pop(tid, None)
        if r == 'stick':
            self.svec = (0.0, 0.0); self.sbase = None; self.sknob = None
        elif r:
            self.release(r)

    def key_down(self, k):
        self.keys.add(k)
        if self.mode == 'title' and k in (pygame.K_RETURN, pygame.K_SPACE):
            self.begin_select(); return
        if self.mode == 'over' and k in (pygame.K_RETURN, pygame.K_SPACE) and self.over_t > 60:
            self.begin_select(); return
        if self.mode == 'select':
            if k in (pygame.K_LEFT, pygame.K_RIGHT):
                self.select_side = 1-self.select_side
            elif k in (pygame.K_RETURN, pygame.K_SPACE):
                self.start()
            elif k in (pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6, pygame.K_7, pygame.K_8):
                idx = k - pygame.K_1
                if self.select_side == 0: self.p1_choice = idx
                else: self.cpu_choice = idx
            return
        if k in (pygame.K_j, pygame.K_z):
            self.press('A')
        elif k in (pygame.K_k, pygame.K_x):
            self.press('B')
        elif k == pygame.K_SPACE:
            self.press('J')
        elif k in (pygame.K_i, pygame.K_u):
            self.press('G')

    def key_up(self, k):
        self.keys.discard(k)
        if k in (pygame.K_j, pygame.K_z):
            self.release('A')
        elif k in (pygame.K_k, pygame.K_x):
            self.release('B')
        elif k == pygame.K_SPACE:
            self.release('J')
        elif k in (pygame.K_i, pygame.K_u):
            self.release('G')

    def read_input(self):
        i = Inp()
        i.x, i.y = self.svec
        ks = self.keys
        if ks:
            kx = (1 if (pygame.K_RIGHT in ks or pygame.K_d in ks) else 0) - \
                 (1 if (pygame.K_LEFT in ks or pygame.K_a in ks) else 0)
            ky = (1 if (pygame.K_UP in ks or pygame.K_w in ks) else 0) - \
                 (1 if (pygame.K_DOWN in ks or pygame.K_s in ks) else 0)
            if kx or ky:
                i.x, i.y = float(kx), float(ky)
        i.jump_held = self.jump_held
        i.a = self.edge['a']; i.b = self.edge['b']; i.jump = self.edge['jump']
        i.grab = self.edge['grab']; i.shield = 'S' in self.btn_down or pygame.K_l in ks
        self.edge['a'] = self.edge['b'] = self.edge['jump'] = self.edge['grab'] = False
        return i

    # ---------- 更新 ----------
    def update(self, dt):
        self.acc += min(dt, 0.1)
        n = 0
        while self.acc >= DT and n < 4:
            self.acc -= DT
            n += 1
            self.frame_no += 1
            if self.mode == 'play':
                self.step()
            elif self.mode in ('title', 'select'):
                for f in self.fs:
                    f.tick(Inp(), self)
                self.update_fx()
            else:
                self.over_t += 1
                self.update_fx()
                for f in self.fs:
                    if f.state != 'dead':
                        f.tick(Inp(), self)
            self.update_cam()

    def step(self):
        pin = self.read_input()
        for f in self.fs:
            inp = pin if f is self.p1 else ai_input(f, self.p1, self)
            f.tick(inp, self)
        self.check_hits(self.p1, self.p2)
        self.check_hits(self.p2, self.p1)
        self.update_fireballs()
        self.update_fx()
        for f in self.fs:
            if f.state != 'dead' and (f.x < BLAST_L or f.x > BLAST_R or f.y > BLAST_T or f.y < BLAST_B):
                self.ko(f)

    def ko(self, f):
        f.stocks -= 1
        f.state = 'dead'; f.ko_timer = 75
        f.atk = None; f.carry = None
        ex = clamp(f.x, BLAST_L, BLAST_R); ey = clamp(f.y, BLAST_B, BLAST_T)
        self.fx.append(dict(k='ko', x=ex, y=ey, life=34, max=34))
        self.shake = 16
        if f.stocks <= 0:
            self.mode = 'over'
            self.winner = self.other(f)
            self.over_t = 0

    def check_hits(self, att, tgt):
        if att.state != 'attack' or att.atk is None or att.hitlag > 0:
            return
        if tgt.state == 'dead' or tgt.inv > 0 or tgt.plat > 0:
            return
        A = ATTACKS[att.atk]
        for i, hb in enumerate(A['hits']):
            if not (hb['s'] <= att.af <= hb['e']):
                continue
            key = hb.get('grp', i)
            last = att.hit_log.get(key)
            if last is not None:
                rh = hb.get('rehit')
                if not rh or att.af - last < rh:
                    continue
            hx = att.x + att.face*hb['x']; hy = att.y + hb['y']
            if tgt.hurt_overlap(hx, hy, hb['r']):
                if hb.get('grab'):
                    if tgt.state != 'shield' and tgt.stun <= 0:
                        tgt.pct = min(999.0, tgt.pct + 3.0)
                        tgt.stun = 24
                        tgt.state = 'hit'; tgt.atk = None
                        tgt.kbx = att.face*0.45; tgt.kby = 0.1
                        tgt.vx = tgt.vy = 0.0
                        self.fx.append(dict(k='spark', x=hx, y=hy, life=10, max=10, sz=7))
                    else:
                        att.lag = 12
                    att.hit_log[key] = att.af
                    return
                if tgt.state == 'shield':
                    tgt.shield_hp = max(0.0, getattr(tgt, 'shield_hp', 50.0) - hb['d']*1.7)
                    tgt.stun = max(tgt.stun, int(hb['d']*0.45))
                    att.hit_log[key] = att.af
                    self.fx.append(dict(k='spark', x=hx, y=hy, life=8, max=8, sz=5))
                    if tgt.shield_hp <= 0:
                        tgt.state = 'hit'; tgt.stun = 70; tgt.kbx = att.face*0.2; tgt.kby = 0
                    return
                att.hit_log[key] = att.af
                self.apply_hit(att, tgt, hb, att.face, hx, hy, True)
                return

    def apply_hit(self, att, tgt, hb, dirx, hx, hy, att_lag):
        """本家の吹っ飛ばし計算式:
           KB = ((((p/10 + p*d/20) * 200/(w+100) * 1.4) + 18) * 成長/100) + 固定
           (p = ダメージ加算後の%, d = 技のダメージ, w = 体重)
           初速 = KB*0.03 / 硬直F = KB*0.4 / 毎F 0.051 ずつ減速"""
        d = hb['d']
        tgt.pct = min(999.0, tgt.pct + d)
        p = tgt.pct
        kb = ((((p/10.0) + (p*d/20.0))*(200.0/(tgt.W + 100.0))*1.4) + 18.0)*(hb['g']/100.0) + hb['b']
        ang = hb['a']
        if ang == 361:                       # サクライ角
            ang = 0 if (tgt.grounded and kb < 32) else 44
        spd = kb*0.03
        rad = math.radians(ang)
        tgt.kbx = math.cos(rad)*spd*dirx
        tgt.kby = math.sin(rad)*spd
        tgt.vx = 0.0; tgt.vy = 0.0
        if tgt.kby > 0.01 and tgt.grounded:
            tgt.grounded = False
            tgt.y += 0.2
        tgt.stun = max(1, int(kb*0.4))
        tgt.ledge_grabs = 0
        tgt.ledge_inv_delay = 0; tgt.ledge_inv_eligible = False
        tgt.state = 'hit'; tgt.atk = None; tgt.helpless = False; tgt.carry = None
        tgt.fastfall = False
        tgt.tumble = (kb >= 32) and not hb.get('carry')
        tgt.tumble_dir = -1 if tgt.kbx > 0 else 1
        if hb.get('turn'):
            tgt.face = -tgt.face
        if hb.get('carry') and att is not None:
            att.carry = tgt; tgt.carried_by = att
        else:
            tgt.carried_by = None
        lag = int(min(20, d/3.0 + 3))
        tgt.hitlag = lag; tgt.shake = lag
        if att_lag and att is not None:
            att.hitlag = lag
        self.fx.append(dict(k='spark', x=hx, y=hy, life=10, max=10, sz=5 + d*0.8))
        if kb > 55:
            self.shake = max(self.shake, min(12, int(kb/9)))

    def reflect(self, f):
        bx = f.x + f.face*9; by = f.y + 10
        for p in self.fireballs:
            if p.owner is not f and abs(p.x - bx) < 11 and abs(p.y - by) < 12:
                p.owner = f; p.vx = -p.vx*1.4; p.vy = abs(p.vy)*0.5
                p.refl = True; p.life = max(p.life, 80)
                self.fx.append(dict(k='spark', x=p.x, y=p.y, life=10, max=10, sz=9))

    def update_fireballs(self):
        keep = []
        for p in self.fireballs:
            p.life -= 1
            p.vy -= 0.11
            p.x += p.vx; p.y += p.vy
            if p.vy < 0 and abs(p.x) < STAGE_HW and p.y <= p.r and p.y > -4:
                p.y = p.r; p.vy = 1.35
            hit = False
            for t in self.fs:
                if t is p.owner or t.state == 'dead' or t.inv > 0 or t.plat > 0:
                    continue
                if t.hurt_overlap(p.x, p.y, p.r):
                    hb = dict(d=7 if p.refl else 5, a=361, b=8, g=25)
                    self.apply_hit(p.owner, t, hb, 1 if p.vx >= 0 else -1, p.x, p.y, False)
                    hit = True
                    break
            if hit or p.life <= 0 or abs(p.x) > BLAST_R + 20 or p.y < BLAST_B:
                continue
            if abs(p.x) < STAGE_HW and -BODY_T < p.y < -0.5:
                continue
            keep.append(p)
        self.fireballs = keep

    def puff(self, x, y):
        self.fx.append(dict(k='puff', x=x, y=y, life=14, max=14))

    def update_fx(self):
        for e in self.fx:
            e['life'] -= 1
            if e['k'] == 'water':
                e['x'] += e['vx']; e['y'] += e['vy']; e['vy'] -= 0.04
        self.fx = [e for e in self.fx if e['life'] > 0]
        if self.shake > 0:
            self.shake -= 1

    def update_cam(self):
        al = [f for f in self.fs if f.state != 'dead'] or self.fs
        xs = [clamp(f.x, -125, 125) for f in al]
        ys = [clamp(f.y, -40, 100) for f in al]
        mx = (max(xs) + min(xs))*0.5
        spread = max(xs) - min(xs)
        vs = max(ys) - min(ys)
        ty = clamp((max(ys) + min(ys))*0.5 + 12, 4, 70)
        D = max(150.0, 0.85*spread + 88.0, (vs*0.5 + 44.0)/0.44)
        D = min(D, 380.0)
        c = self.cam
        c.tx += (mx - c.tx)*0.08
        c.ty += (ty - c.ty)*0.08
        c.dist += (D - c.dist)*0.06
        if self.shake > 0:
            c.ox = random.uniform(-1, 1)*self.shake*0.8
            c.oy = random.uniform(-1, 1)*self.shake*0.8
        else:
            c.ox = c.oy = 0.0

    # ---------- 描画ヘルパー ----------
    def font(self, size):
        f = self.fonts.get(size)
        if f is None:
            f = pygame.font.Font(self.jp_font, size)
            self.fonts[size] = f
        return f

    def text(self, s, size, col, x, y, w=0, align='left'):
        try:
            img = self.font(size).render(s, True, self.rgb(col))
        except Exception:
            return
        if align == 'center':
            x = x + (w - img.get_width())/2
        self.screen.blit(img, (int(x), int(y)))

    @staticmethod
    def rgb(c):
        return (int(clamp(c[0], 0, 1)*255), int(clamp(c[1], 0, 1)*255), int(clamp(c[2], 0, 1)*255))

    def poly(self, pts, col):
        ip = [(int(x), int(y)) for x, y in pts]
        rgb = self.rgb(col)
        pygame.draw.polygon(self.screen, rgb, ip)
        pygame.draw.polygon(self.screen, rgb, ip, 1)

    def apoly(self, pts, col):
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
        x0 = int(min(xs)) - 2; y0 = int(min(ys)) - 2
        w = int(max(xs)) - x0 + 4; h = int(max(ys)) - y0 + 4
        if w <= 0 or h <= 0 or w > 3000 or h > 3000:
            return
        t = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.polygon(t, self.rgb(col) + (int(clamp(col[3], 0, 1)*255),),
                            [(int(x) - x0, int(y) - y0) for x, y in pts])
        self.screen.blit(t, (x0, y0))

    def acircle(self, cx, cy, r, col):
        r = int(r)
        if r < 1:
            return
        t = pygame.Surface((r*2 + 2, r*2 + 2), pygame.SRCALPHA)
        pygame.draw.circle(t, self.rgb(col) + (int(clamp(col[3], 0, 1)*255),), (r + 1, r + 1), r)
        self.screen.blit(t, (int(cx) - r - 1, int(cy) - r - 1))

    def arect(self, x, y, w, h, col):
        w = int(w); h = int(h)
        if w < 1 or h < 1:
            return
        t = pygame.Surface((w, h), pygame.SRCALPHA)
        t.fill(self.rgb(col) + (int(clamp(col[3], 0, 1)*255),))
        self.screen.blit(t, (int(x), int(y)))

    def circle(self, cx, cy, r, col):
        if r >= 1:
            pygame.draw.circle(self.screen, self.rgb(col), (int(cx), int(cy)), int(r))

    # ---------- 描画 ----------
    def draw(self):
        W, H = self.W, self.H
        cam = self.cam
        cam.setup(W, H)
        self.draw_bg(W, H)
        self.draw_stage(cam)
        for f in self.fs:
            if f.state != 'dead' and abs(f.x) < STAGE_HW + 4 and f.y > -0.5:
                sy = 1.0/(1.0 + f.y*0.04)
                pts = []
                for k in range(14):
                    a = k*TAU/14
                    q = cam.proj(f.x + math.cos(a)*5.0*sy, 0.05, math.sin(a)*3.0*sy)
                    pts.append((q[0], q[1]))
                self.apoly(pts, (0, 0, 0, 0.30))
        polys = []
        for f in self.fs:
            self.fighter_polys(f, polys)
        polys.sort(key=lambda q: -q[0])
        for _d, pts, col in polys:
            self.poly(pts, col)
        self.draw_projectiles(cam)
        self.draw_fx(cam, W, H)
        if SHOW_HITBOX:
            self.draw_hitboxes(cam)
        self.draw_hud(W, H)
        self.draw_controls(W, H)
        self.draw_overlay(W, H)

    def draw_bg(self, W, H):
        scr = self.screen
        n = 18
        for k in range(n):
            u = k/float(n-1)
            scr.fill(((8 + 24*u), (6 + 12*u), (30 + 62*u)),
                     (0, int(H*k/n), W, int(H/float(n)) + 2))
        cx = W*0.5 - self.cam.tx*0.25; cy = H*0.30
        for i in range(6, -1, -1):
            r = 40 + i*34
            c = (15 + (7 - i)*4, 10 + (7 - i)*3, 49 + (7 - i)*8)
            pygame.draw.ellipse(scr, c, (int(cx - r*1.6), int(cy - r*0.6), int(r*3.2), int(r*1.2)))
        for (u, v, s) in self.stars:
            sx = (u*W*1.5 - self.cam.tx*0.8*(0.3 + s)) % W
            sy = v*H*0.8
            tw = 0.5 + 0.5*math.sin(self.frame_no*0.05 + s*20)
            b = int(255*clamp(0.25 + 0.6*tw*s + 0.2, 0, 1))
            sz = int(1.5 + s*1.5)
            scr.fill((b, b, b), (int(sx), int(sy), sz, sz))

    def draw_stage(self, cam):
        S = STAGE_HW; D = STAGE_DZ
        T = [(-S, 0, -D), (S, 0, -D), (S, 0, D), (-S, 0, D)]
        M = [(-S, -5, -D), (S, -5, -D), (S, -5, D), (-S, -5, D)]
        B = [(-28, -15, -8), (28, -15, -8), (28, -15, 8), (-28, -15, 8)]
        ctr = (0, -6, 0)
        out = []
        poly3(cam, T, (0.55, 0.62, 0.86), ctr, out)
        for i in range(4):
            j = (i + 1) % 4
            poly3(cam, [T[i], T[j], M[j], M[i]], (0.24, 0.29, 0.52), ctr, out)
            poly3(cam, [M[i], M[j], B[j], B[i]], (0.15, 0.18, 0.37), ctr, out)
        poly3(cam, B, (0.10, 0.10, 0.22), ctr, out)
        # 小戦場風の左右2つの台。箱の上面が着地面になる。
        for px, py, phw, pd in PLATFORMS:
            add_box(out, cam, (IDENT, (px, py - 0.65, 0.0)),
                    (0, 0, 0), (phw, 0.65, pd), (0.42, 0.72, 0.92))
        for _d, pts, col in sorted(out, key=lambda item: item[0], reverse=True):
            self.poly(pts, col)
        # 台の縁を明るくして、足場の位置を見やすくする
        for px, py, phw, pd in PLATFORMS:
            corners = [(px-phw, py, -pd), (px+phw, py, -pd),
                       (px+phw, py, pd), (px-phw, py, pd)]
            q = [cam.proj(*v) for v in corners]
            pygame.draw.lines(self.screen, self.rgb((0.75, 0.95, 1.0)), True,
                              [(int(v[0]), int(v[1])) for v in q], 2)
        gc = self.rgb((0.72, 0.80, 0.95))
        for k in range(-4, 5):
            gx = k*S/4.5
            a = cam.proj(gx, 0.02, -D); b = cam.proj(gx, 0.02, D)
            pygame.draw.line(self.screen, gc, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), 1)
        for gz in (-D*0.5, 0, D*0.5):
            a = cam.proj(-S, 0.02, gz); b = cam.proj(S, 0.02, gz)
            pygame.draw.line(self.screen, gc, (int(a[0]), int(a[1])), (int(b[0]), int(b[1])), 1)
        q = [cam.proj(*t) for t in T]
        pygame.draw.lines(self.screen, self.rgb((0.75, 0.95, 1.0)), True,
                          [(int(p[0]), int(p[1])) for p in q], 3)

    def fighter_polys(self, f, polys):
        cam = self.cam
        if f.state == 'dead' or f.pose is None:
            return
        if f.plat > 0:
            add_box(polys, cam, (IDENT, (f.x, 61.0, 0.0)), (0, 0, 0), (9, 0.6, 9), (0.95, 0.85, 0.35))
        if f.inv > 0 and (f.t // 3) % 2 == 0 and f.plat <= 0 and f.state != 'ledge':
            return
        p = f.pose; pal = f.pal
        if f.state == 'shield':
            q = cam.proj(f.x, f.y + 9.0, 0.0)
            rad = 13.0*cam.fl/max(1.0, q[2])
            self.acircle(q[0], q[1], rad, (0.25, 0.65, 1.0, 0.28))
            pygame.draw.circle(self.screen, self.rgb((0.45, 0.8, 1.0)),
                               (int(q[0]), int(q[1])), max(2, int(rad)), 2)
            self.arect(q[0]-18, q[1]-rad-12, 36*(f.shield_hp/50.0), 4, (0.35, 0.8, 1.0, 0.9))
        Rf = rz(f.flip)
        R = mm(Rf, ry(f.yaw + p['spin']))
        c = (0.0, 9.0, 0.0)
        rc = mv(Rf, c)
        sk = random.uniform(-0.6, 0.6) if (f.hitlag > 0 and f.shake > 0) else 0.0
        base = (R, (f.x + sk + c[0] - rc[0], f.y + c[1] - rc[1], c[2] - rc[2]))
        pel = child(base, 0.0, (p['dx'], 7.6 + p['dy'], 0.0))
        add_box(polys, cam, pel, (0, 0, 0), (2.7, 1.0, 3.0), pal['pants'])
        # 脚
        for side, la, ka in ((1, p['lF'], p['kF']), (-1, p['lB'], p['kB'])):
            hip = child(pel, la, (0.0, -0.4, 1.7*side))
            add_box(polys, cam, hip, (0, -1.7, 0), (1.25, 1.7, 1.25), pal['pants'])
            knee = child(hip, ka, (0.0, -3.4, 0.0))
            add_box(polys, cam, knee, (0, -1.7, 0), (1.15, 1.7, 1.15), pal['pants'])
            ank = child(knee, 0.0, (0.0, -3.4, 0.0))
            add_box(polys, cam, ank, (0.8, 0.0, 0), (1.9, 0.4, 1.3), pal['shoe'])
        # 胴体
        tor = child(pel, -p['lean'], (0.0, 0.4, 0.0))
        add_box(polys, cam, tor, (0, 1.7, 0), (2.6, 1.5, 3.0), pal['pants'])
        add_box(polys, cam, tor, (0, 4.4, 0), (2.7, 1.3, 3.2), pal['shirt'])
        # 腕
        for side, a, e in ((1, p['aF'], p['eF']), (-1, p['aB'], p['eB'])):
            sh = child(tor, a, (0.0, 5.0, 3.9*side))
            add_box(polys, cam, sh, (0, -1.5, 0), (0.95, 1.5, 0.95), pal['shirt'])
            el = child(sh, e, (0.0, -3.0, 0.0))
            add_box(polys, cam, el, (0, -1.3, 0), (0.85, 1.3, 0.85), pal['shirt'])
            add_box(polys, cam, el, (0, -3.0, 0), (1.1, 0.9, 1.1), pal['glove'])
        # 頭
        hd = child(tor, -p['head'], (0.0, 5.7, 0.0))
        add_box(polys, cam, hd, (0, 2.5, 0), (2.8, 2.5, 2.9), pal['skin'])
        add_box(polys, cam, hd, (0, 4.6, 0), (3.1, 1.1, 3.2), pal['hat'])
        add_box(polys, cam, hd, (3.3, 3.9, 0), (1.7, 0.35, 2.6), pal['hat'])
        add_box(polys, cam, hd, (3.0, 2.2, 0), (0.8, 0.8, 0.8), pal['skin'])
        add_box(polys, cam, hd, (2.9, 1.1, 0), (0.5, 0.4, 1.9), pal['hair'])
        add_box(polys, cam, hd, (-2.6, 2.2, 0), (0.8, 1.4, 2.6), pal['hair'])
        add_box(polys, cam, hd, (2.85, 3.0, 1.0), (0.2, 0.55, 0.3), pal['eye'])
        add_box(polys, cam, hd, (2.85, 3.0, -1.0), (0.2, 0.55, 0.3), pal['eye'])
        # キャラクターごとの簡易シルエット装備
        if f.char_id == 2:  # ピーチの王冠
            add_box(polys, cam, hd, (0.0, 5.45, 0.0), (1.8, 0.45, 1.8), (1.0, 0.78, 0.12))
            add_box(polys, cam, hd, (0.0, 6.0, 0.0), (0.35, 0.55, 0.35), (1.0, 0.25, 0.35))
        elif f.char_id == 3:  # クッパ風の甲羅とトゲ
            add_box(polys, cam, tor, (-1.1, 2.2, -2.2), (2.2, 2.4, 1.0), (0.16, 0.48, 0.18))
            for zz in (-2.4, 0.0, 2.4):
                add_box(polys, cam, tor, (-1.1, 4.0, zz), (0.65, 1.0, 0.65), (0.95, 0.82, 0.55))
        elif f.char_id == 4:  # リンク風の剣と盾
            sword = child(tor, -0.25, (0.0, 1.5, 4.9))
            add_box(polys, cam, sword, (0.0, -2.0, 0.0), (0.45, 3.0, 0.45), (0.78, 0.88, 1.0))
            add_box(polys, cam, sword, (0.0, -3.7, 0.0), (1.2, 0.35, 0.6), (0.95, 0.72, 0.18))
            add_box(polys, cam, tor, (0.0, 2.3, -4.7), (1.8, 2.1, 0.6), (0.15, 0.32, 0.68))
        elif f.char_id == 5:  # カービィ風の丸いほっぺ
            add_box(polys, cam, hd, (3.0, 1.8, 1.55), (0.35, 0.45, 0.25), (1.0, 0.2, 0.38))
            add_box(polys, cam, hd, (3.0, 1.8, -1.55), (0.35, 0.45, 0.25), (1.0, 0.2, 0.38))
        elif f.char_id == 6:  # サムス風のアームキャノン
            add_box(polys, cam, tor, (4.7, 1.0, 4.8), (1.5, 1.8, 1.5), (0.92, 0.48, 0.08))
            add_box(polys, cam, tor, (5.8, 1.0, 4.8), (1.2, 1.1, 1.1), (0.25, 0.8, 1.0))
        elif f.char_id == 7:  # フォックス風の尻尾
            add_box(polys, cam, tor, (-3.5, -0.3, 0.0), (2.4, 1.0, 1.3), (0.88, 0.65, 0.36))
            add_box(polys, cam, tor, (-4.8, -0.1, 0.0), (1.0, 0.55, 0.8), (0.95, 0.9, 0.78))
        # ポンプ(下B)
        if f.state == 'attack' and f.atk == 'fludd':
            add_box(polys, cam, tor, (-3.6, 3.0, 0), (1.3, 2.4, 1.9), (0.25, 0.6, 1.0))
            add_box(polys, cam, tor, (6.2, 1.2, 0), (2.4, 0.7, 0.7), (0.55, 0.85, 1.0))
        # マント(横B)
        if f.state == 'attack' and f.atk == 'cape' and 4 <= f.af <= 18:
            u = (f.af - 4)/14.0
            L = 15.0*math.sin(u*math.pi)
            fx = f.face
            q = [cam.proj(f.x + fx*2.0, f.y + 15.0, 4.0),
                 cam.proj(f.x + fx*(2.0 + L), f.y + 14.0, 4.0),
                 cam.proj(f.x + fx*(2.0 + L*0.8), f.y + 3.0, 4.0),
                 cam.proj(f.x + fx*2.0, f.y + 4.0, 4.0)]
            polys.append((min(z[2] for z in q) - 3.0, [(z[0], z[1]) for z in q], (1.0, 0.85, 0.2, 0.88)))

    def draw_projectiles(self, cam):
        for p in self.fireballs:
            sx, sy, dp = cam.proj(p.x, p.y, 0.0)
            r = p.r*cam.fl/dp
            self.acircle(sx, sy, r*1.7, (1.0, 0.5, 0.1, 0.35))
            self.circle(sx, sy, r, (1.0, 0.55, 0.1) if not p.refl else (1.0, 0.3, 0.6))
            self.circle(sx, sy, r*0.5, (1.0, 0.95, 0.5))

    def draw_fx(self, cam, W, H):
        for e in self.fx:
            u = e['life']/float(e['max'])
            sx, sy, dp = cam.proj(e['x'], e['y'], 2.0)
            k = cam.fl/dp
            if e['k'] == 'spark':
                r = e['sz']*k*(0.5 + (1 - u))
                self.poly(star_pts(sx, sy, r, 8, 0.35, e['life']*0.3), (1.0, 0.95, 0.5))
                self.poly(star_pts(sx, sy, r*0.55, 8, 0.4, -e['life']*0.3), (1.0, 1.0, 1.0))
            elif e['k'] == 'water':
                self.circle(sx, sy, 1.7*k, (0.45, 0.8, 1.0))
            elif e['k'] == 'puff':
                r = (2.0 + (1 - u)*6.0)*k
                pygame.draw.ellipse(self.screen, (230, 230, 240),
                                    (int(sx - r), int(sy - r*0.5), int(r*2), int(r)), 2)
            elif e['k'] == 'ko':
                x2 = clamp(sx, 30, W - 30); y2 = clamp(sy, 30, H - 30)
                r = 140*(1 - u*0.4)
                self.poly(star_pts(x2, y2, r, 10, 0.18, 0.2), (1.0, 1.0, 0.7))
                self.poly(star_pts(x2, y2, r*0.5, 10, 0.3, 0.0), (1.0, 0.4, 0.3))

    def draw_hitboxes(self, cam):
        for f in self.fs:
            if f.state == 'attack' and f.atk:
                for hb in ATTACKS[f.atk]['hits']:
                    if hb['s'] <= f.af <= hb['e']:
                        sx, sy, dp = cam.proj(f.x + f.face*hb['x'], f.y + hb['y'], 3.0)
                        self.acircle(sx, sy, hb['r']*cam.fl/dp, (1, 0, 0, 0.35))

    def move_label(self, key):
        return ATTACKS[key]['jp'] if self.jp_font else MOVE_EN[key]

    def draw_hud(self, W, H):
        for f, xc in ((self.p1, W*0.5 - 118), (self.p2, W*0.5 + 118)):
            self.arect(xc - 100, H - 106, 200, 92, (0, 0, 0, 0.55))
            p = f.pct
            if p < 50:
                col = (1, 1, 1)
            elif p < 100:
                col = (1, 0.9, 0.3)
            elif p < 150:
                col = (1, 0.55, 0.15)
            else:
                col = (1, 0.2, 0.2)
            self.text('%d%%' % int(p), 52, col, xc - 100, H - 106, 200, 'center')
            self.text(f.name, 20, (0.8, 0.9, 1), xc - 94, H - 52)
            for s in range(f.stocks):
                self.circle(xc + 30 + s*26, H - 42, 10, f.pal['hat'])
            if f.last_move[1] > 0:
                self.text(self.move_label(f.last_move[0]), 24, (1, 1, 0.6), xc - 190, H - 140, 380, 'center')
        self.arect(W - 112, 14, 98, 38, (1, 1, 1, 0.25))
        self.text('RESTART', 20, (1, 1, 1), W - 112, 23, 98, 'center')

    def draw_controls(self, W, H):
        if self.mode != 'play':
            return
        if self.sbase:
            bx, by = self.sbase; kx, ky = self.sknob
            self.acircle(bx, by, 62, (1, 1, 1, 0.14))
            self.acircle(kx, ky, 28, (1, 1, 1, 0.5))
        else:
            bx, by = W*0.14, H - 150
            self.acircle(bx, by, 62, (1, 1, 1, 0.08))
            self.text(self.L('スティック', 'STICK'), 18, (0.6, 0.6, 0.7), bx - 60, by - 9, 120, 'center')
        labels = {'A': self.L('攻撃', 'ATTACK'), 'B': self.L('必殺', 'SPECIAL'), 'J': self.L('ジャンプ', 'JUMP'), 'S': self.L('シールド', 'SHIELD'), 'G': self.L('つかみ', 'GRAB')}
        cols = {'A': (1, 0.4, 0.4), 'B': (0.4, 0.7, 1), 'J': (0.5, 1, 0.5), 'S': (0.25, 0.65, 1), 'G': (1, 0.65, 0.25)}
        for name, (x, y, r) in self.btns(W, H).items():
            on = name in self.btn_down
            self.acircle(x, y, r, cols[name] + ((0.65 if on else 0.28),))
            self.text(labels[name], 22, (1, 1, 1), x - r, y - 10, r*2, 'center')

    def draw_overlay(self, W, H):
        if self.mode == 'title':
            self.arect(0, H*0.08, W, H*0.62, (0, 0, 0, 0.55))
            self.text('SMASH MARIO 3D', 64, (1, 0.85, 0.2), 0, H*0.10, W, 'center')
            lines = [self.L('左半分をタッチ: スティック   右: 攻撃(A) / 必殺(B) / ジャンプ',
                            'Left side: stick   Right: ATTACK(A) / SPECIAL(B) / JUMP'),
                     self.L('A: 弱(ニュートラル) 上強(上) 下強(下) 横強(横)',
                            'A: Jab(neutral) Up/Down/Forward tilt'),
                     self.L('B: N=ファイアボール 横=マント 上=スーパージャンプパンチ 下=ポンプ',
                            'B: N=Fireball Side=Cape Up=Super Jump Punch Down=F.L.U.D.D.'),
                     self.L('%が溜まるほど吹っ飛ぶ！ ストック3 / 場外に飛ばして倒そう',
                            'More % = more knockback! 3 stocks. Knock them off the stage!'),
                     self.L('タップしてキャラ選択へ', 'TAP FOR CHARACTER SELECT')]
            for i, t in enumerate(lines):
                self.text(t, 28 if i < 4 else 40, (1, 1, 1), 0, H*0.25 + i*40, W, 'center')
        elif self.mode == 'select':
            self.arect(0, 0, W, H, (0.025, 0.035, 0.09, 0.96))
            self.text(self.L('キャラクターセレクト', 'CHARACTER SELECT'), 44, (1, 0.88, 0.28), 0, H*0.035, W, 'center')
            tab_y = int(H*0.19)
            self.arect(W*0.08, tab_y-27, W*0.38, 54, (0.12, 0.42, 0.95, 0.8 if self.select_side == 0 else 0.3))
            self.arect(W*0.54, tab_y-27, W*0.38, 54, (0.95, 0.36, 0.18, 0.8 if self.select_side == 1 else 0.3))
            self.text(self.L('プレイヤー：', 'PLAYER: ') + ROSTER[self.p1_choice]['name'], 25, (1,1,1), W*0.08, tab_y-14, W*0.38, 'center')
            self.text(self.L('CPU：', 'CPU: ') + ROSTER[self.cpu_choice]['name'], 25, (1,1,1), W*0.54, tab_y-14, W*0.38, 'center')
            cols, gap = 4, max(10, int(W*0.014))
            margin = max(16, int(W*0.035))
            card_w = (W - margin*2 - gap*(cols-1)) / cols
            card_h = min(H*0.19, 118)
            start_y = H*0.29
            for idx, ch in enumerate(ROSTER):
                col, row = idx % cols, idx // cols
                x0 = margin + col*(card_w+gap); y0 = start_y + row*(card_h+gap)
                selected = idx == (self.p1_choice if self.select_side == 0 else self.cpu_choice)
                self.arect(x0, y0, card_w, card_h, (0.12,0.16,0.25,0.96))
                edge = (1.0,0.85,0.2) if selected else (0.35,0.45,0.62)
                pygame.draw.rect(self.screen, self.rgb(edge), (int(x0),int(y0),int(card_w),int(card_h)), 4 if selected else 2)
                pal = ch['pal']
                self.acircle(x0+card_w*0.5, y0+card_h*0.39, min(24,card_h*0.23), pal['hat']+(0.98,))
                self.circle(x0+card_w*0.5, y0+card_h*0.39, min(19,card_h*0.18), pal['shirt'])
                self.text(ch['name'], 23, (1,1,1), x0, y0+card_h*0.68, card_w, 'center')
                self.text('番号 '+str(idx+1) if self.jp_font else str(idx+1), 15, (0.72,0.8,0.94), x0, y0+card_h*0.84, card_w, 'center')
            self.arect(W*0.34, H*0.82, W*0.32, H*0.10, (0.12,0.65,0.32,0.95))
            self.text(self.L('対戦スタート', 'START MATCH'), 32, (1,1,1), W*0.34, H*0.845, W*0.32, 'center')
            self.text(self.L('上の欄でプレイヤー/CPUを選び、キャラをタップ', 'Choose PLAYER or CPU, then tap a fighter'), 18, (0.75,0.82,0.95), 0, H*0.94, W, 'center')
        elif self.mode == 'over':
            self.arect(0, H*0.25, W, H*0.34, (0, 0, 0, 0.55))
            win = self.winner is self.p1
            self.text('GAME SET!', 70, (1, 0.9, 0.3), 0, H*0.27, W, 'center')
            self.text(self.L('あなたの勝ち！', 'YOU WIN!') if win else self.L('CPUの勝ち…', 'CPU WINS...'),
                      44, (1, 1, 1), 0, H*0.27 + 76, W, 'center')
            if self.over_t > 60:
                self.text(self.L('タップでもう一度', 'TAP TO PLAY AGAIN'), 32, (1, 1, 1), 0, H*0.27 + 130, W, 'center')


# ====================================================================
#  メインループ
# ====================================================================
def main():
    pygame.init()
    screen = None
    try:
        screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        if screen.get_width() < 320 or screen.get_height() < 240:
            screen = None
    except Exception:
        screen = None
    if screen is None:
        screen = pygame.display.set_mode((1024, 768))
    pygame.display.set_caption('Smash Mario 3D')
    W, H = screen.get_size()
    g = Game(screen)
    clock = pygame.time.Clock()
    FD = getattr(pygame, 'FINGERDOWN', -1)
    FM = getattr(pygame, 'FINGERMOTION', -2)
    FU = getattr(pygame, 'FINGERUP', -3)
    last = time.time()
    running = True
    while running:
        for e in pygame.event.get():
            t = e.type
            if t == pygame.QUIT:
                running = False
            elif t == FD:
                g.seen_finger = True
                g.touch_down(('f', getattr(e, 'finger_id', 0)), e.x*W, e.y*H)
            elif t == FM:
                g.touch_move(('f', getattr(e, 'finger_id', 0)), e.x*W, e.y*H)
            elif t == FU:
                g.touch_up(('f', getattr(e, 'finger_id', 0)))
            elif t == pygame.MOUSEBUTTONDOWN and not g.seen_finger:
                g.touch_down('m', e.pos[0], e.pos[1])
            elif t == pygame.MOUSEMOTION and not g.seen_finger and e.buttons[0]:
                g.touch_move('m', e.pos[0], e.pos[1])
            elif t == pygame.MOUSEBUTTONUP and not g.seen_finger:
                g.touch_up('m')
            elif t == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    running = False
                else:
                    g.key_down(e.key)
            elif t == pygame.KEYUP:
                g.key_up(e.key)
        now = time.time()
        g.update(now - last)
        last = now
        g.draw()
        pygame.display.flip()
        clock.tick(60)
    pygame.quit()


if __name__ == '__main__':
    main()