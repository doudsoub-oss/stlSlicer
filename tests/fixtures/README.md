# Test fixtures

Almost every fixture is generated in code (`tests/conftest.py`, catalogue in PLAN.md Appendix D).
The only committed meshes are the real models in `real/`, used by the end-to-end suite
(`tests/e2e/cases.py`). To add one, see CONTRIBUTING.md, "Add a test fixture".

## Real models

Three 3D scans of plaster casts from the Royal Cast Collection of
[SMK, the National Gallery of Denmark](https://www.smk.dk/). SMK dedicated each scan to the public
domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) on its
[Sketchfab account](https://sketchfab.com/smkmuseum), and its open data API lists the works as
public domain ([Public Domain Mark 1.0](https://creativecommons.org/publicdomain/mark/1.0/)).
The API record of each work links to the Sketchfab page below.

| File | Work | SMK inventory | Licence page | Source STL |
|---|---|---|---|---|
| `real/discobolus.stl` | Discobolus (the discus thrower), Roman copy with a modern head | KAS1549 | [Sketchfab](https://sketchfab.com/3d-models/discobolus-the-discus-thrower-50f50abf45414ad8a658325df7a5fcb3) | [SMK API](https://api.smk.dk/api/v1/download-3d/n583z0576_smk-discobolus.stl) |
| `real/zeus_artemision.stl` | Zeus or Poseidon from Artemision | KAS2100 | [Sketchfab](https://sketchfab.com/3d-models/zeus-or-poseidon-from-the-artemision-d4876aa609304682945145debedfc77e) | [SMK API](https://api.smk.dk/api/v1/download-3d/7m01br55g_smk-poseidon.stl) |
| `real/memnon.stl` | Memnon, pupil of Herodes Atticus | KAS969 | [Sketchfab](https://sketchfab.com/3d-models/memnon-of-ethiopia-55dad8f5a12544f0b2f40183ef919932) | [SMK API](https://api.smk.dk/api/v1/download-3d/9019s715p_KAS969_small.stl) |

## Changes made to the scans

Downloaded on 2026-11-22. Each was decimated with `Manifold.simplify` (manifold3d 3.5.5) to about
12,000 triangles, keeping its position and units, and written as a binary STL with an all-zero
header.

| File | Source triangles | Tolerance (mm) | Triangles | Volume change | Source SHA-256 |
|---|---|---|---|---|---|
| `real/discobolus.stl` | 199,764 | 0.2824 | 11,808 | −1.922 % | `817a9cd22c0f4f346d2112a11c502db23302e25d33db10eb7d3da54b2fb768b1` |
| `real/zeus_artemision.stl` | 209,494 | 0.2335 | 11,796 | −2.294 % | `855a92ebe9d5b6133328b0d2bfb427e27c8d11bf8e82ac763fefacff39509179` |
| `real/memnon.stl` | 399,944 | 0.3488 | 11,924 | −0.741 % | `a9f26bdcb2ce1177a646188cf76fdf6a947c96153fafbe91f7ffe071f5e97125` |

The scans are about 130 mm tall, so the end-to-end cases run them at `--scale 3` to get real cuts.
