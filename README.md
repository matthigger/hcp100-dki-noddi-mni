# hcp100-dki-noddi-mni

[![Software DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20645824.svg)](https://doi.org/10.5281/zenodo.20645824)
[![Data DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20645613.svg)](https://doi.org/10.5281/zenodo.20645613)

Reproducible pipeline that produces **DKI + NODDI diffusion-microstructure maps** for the
**100 unrelated HCP-YA (S1200)** subjects in **MNI152NLin2009cAsym at 2 mm**, by running
[QSIRecon](https://github.com/PennLINC/qsirecon) through
[BABS](https://github.com/PennLINC/babs) on a single local machine. Six maps per subject:

- **DKI** (Dipy): `fa`, `md`, `mk` — fit on b ≤ 2000
- **NODDI** (AMICO): `icvf`, `isovf`, `od` — full multishell DWI

Deposited artifacts:

- **Maps (data):** https://zenodo.org/records/20645614
- **Pipeline (this repo, archived):** https://zenodo.org/records/20645825

## How it works

A thin wrapper container (`run_hcp.py` in `Apptainer.def.tmpl`, built `FROM` a digest-pinned
[`pennlinc/qsirecon`](https://hub.docker.com/r/pennlinc/qsirecon) image) runs the two QSIRecon
passes plus the b ≤ 2000 filter and presents BABS an ordinary BIDS App. The recon specs
(`noddi_mni.yaml`, `dki_mni.yaml`) and the TemplateFlow target are baked into the image, so
jobs are hermetic.

## Run it

Edit `config.sh` (paths, FreeSurfer license, SLURM resources), then, in order:

```bash
bash 00_install_env.sh        # micromamba 'babs' env (datalad, git-annex, babs)
sudo bash 01_fix_slurm.sh     # repair the local single-node SLURM (only sudo step)
bash 02_build_sif.sh          # build + register the wrapper container
source ./config.sh && micromamba run -n babs python 03_build_input.py
bash 04_run_babs.sh           # init -> validate one subject -> submit the rest -> merge
```

## Reproducibility & QC

Pinned for reproducibility:

- the [`pennlinc/qsirecon`](https://hub.docker.com/r/pennlinc/qsirecon) container, by digest
- TemplateFlow, baked into the `.sif`
- the toolchain (`environment.yml`)
- the cohort (`subjects.txt`)
- `ANTS_RANDOM_SEED=1` (ANTs registration is multithreaded, so runs reproduce
  within numerical tolerance, not bit-for-bit)

`verify.py <outputs>` checks each subject's six maps — correct space, 2 mm grid,
non-empty brain, and per-parameter value ranges.

`05_brain_mask.py <outputs>` writes one cohort brain mask: the voxels with a
finite, nonzero DKI FA value in *every* subject (the intersection of nonzero-FA
support). It is a property of the whole cohort, so it cannot be recomputed from a
partial download.

## Credit & license

Built on:

- [BABS](https://github.com/PennLINC/babs) — Zhao et al. 2024, *Imaging Neuroscience*
- [QSIRecon](https://github.com/PennLINC/qsirecon)
- **NODDI** (Zhang 2012) / **AMICO** (Daducci 2015)
- **Dipy DKI** — Jensen & Helpern 2010
- [DataLad](https://www.datalad.org)

Code: MIT (`LICENSE`). Derived from HCP-YA S1200 Open Access data under the WU-Minn HCP Open
Access Data Use Terms — register/accept at https://db.humanconnectome.org before use.
