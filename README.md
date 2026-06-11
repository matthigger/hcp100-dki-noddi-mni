# hcp100-dki-noddi-mni — HCP-YA U100 DKI+NODDI microstructure maps (MNI 2 mm) via BABS

A minimal, self-contained project that runs **QSIRecon**'s diffusion reconstruction
on **HCP-Young Adult** data through **BABS** (BIDS App Bootstrap) on a single local
machine, producing six MNI152NLin2009cAsym 2 mm scalar maps per subject:

| model | maps | input |
|-------|------|-------|
| **DKI** (Dipy) | `fa`, `md`, `mk` | b ≤ 2000 shells |
| **NODDI** (AMICO) | `icvf`, `isovf`, `od` | full multishell DWI |

The point of using BABS is reproducible, provenance-tracked processing at scale: the
inputs and every result are tracked in DataLad / git-annex, so the whole run — and the
shareable output — is a versioned dataset, not a pile of loose files.

## Credit

This project is just a thin local harness around other people's tools. Please cite them:

- **BABS** — Zhao C, *et al.* "A reproducible and generalizable software workflow for
  analysis of large-scale neuroimaging data collections using BIDS Apps."
  *Imaging Neuroscience* (2024). doi:[10.1162/imag_a_00074](https://doi.org/10.1162/imag_a_00074).
  Code: https://github.com/PennLINC/babs · Docs: https://pennlinc-babs.readthedocs.io
- **The FAIRly big framework** that BABS implements — Wagner AS, *et al. Sci Data* (2022).
  doi:[10.1038/s41597-022-01163-2](https://doi.org/10.1038/s41597-022-01163-2).
- **QSIRecon** (diffusion reconstruction BIDS App) — PennLINC. https://qsirecon.readthedocs.io
- **NODDI** — Zhang H, *et al. NeuroImage* (2012); **AMICO** fit — Daducci A, *et al.
  NeuroImage* (2015).
- **DKI** — Jensen JH & Helpern JA. *NMR Biomed* (2010).
- **DataLad** / **git-annex** — the data-versioning substrate.
- **HCP** — WU-Minn HCP Consortium. Data used under the HCP Young Adult Open Access
  Data Use Terms; obtain data from https://db.humanconnectome.org.

## How it works

BABS drives one container per subject, treats a non-zero exit as failure, and selects
subjects by BIDS `sub-XXX` id. The HCP recipe needs two QSIRecon passes (NODDI on the
full DWI; DKI on a b ≤ 2000-filtered copy, since the DKI cumulant fit is only valid to
b ≈ 2000–2500), a data-prep step between them, the bare-numeric HCP id with the non-BIDS
`hcpya` layout, and it must tolerate a cosmetic non-zero exit (the hcpya path has no
`dseg`, so QSIRecon's report node crashes after the maps are written).

None of that fits BABS's declarative config, so it lives inside a thin **wrapper container**
(`Apptainer.def.tmpl` + `run_hcp.py`) built `FROM` a digest-pinned `pennlinc/qsirecon` image
(see Pinned versions). BABS sees an ordinary BIDS App; the wrapper runs both passes, applies
the bval filter, and exits 0 iff all six maps exist (`maps.py`). The recon specs
(`noddi_mni.yaml`, `dki_mni.yaml`) and the nipype `linear_plugin.yml` are baked into the image.

## Layout: repo here, runtime elsewhere

This Dropbox-synced folder holds **only source + config**. The BABS runtime lives **outside
Dropbox** at `~/babs_hcp/` (set `BABS_HCP_RUNTIME` in `config.sh`):

```
~/babs_hcp/
  qsirecon-hcp.sif        the wrapper image
  qsirecon-container/     DataLad dataset wrapping the image (for `babs init`)
  input_hcp/              DataLad dataset of HCP inputs (sub-*/T1w/...) — the shareable data
  project/                the BABS project: input_ria + output_ria (git-annex)
  outputs/                a clone of output_ria for retrieving result zips
  compute/                scratch where each job clones + runs
```

This split matters: git-annex object stores and symlink farms must **not** be
Dropbox-synced (it corrupts them and is slow).

## Quickstart

First **edit `config.sh`** — it is the one place that holds every host/dataset-specific
value (runtime location, FreeSurfer license, the source HCP-YA tree, SLURM resources,
the validation subject). At minimum set `BABS_HCP_INPUT_SRC` to your HCP-YA download and
`FS_LICENSE` to your license file. Then run the numbered scripts in order; only step 1
needs `sudo`.

```bash
cd ~/Dropbox/glow/hcp100-dki-noddi-mni
$EDITOR config.sh                            # point the project at your dataset/machine
bash 00_install_env.sh                       # micromamba 'babs' env (datalad, git-annex, babs)
sudo bash 01_fix_slurm.sh                     # repair the local single-node SLURM (only sudo step)
bash 02_build_sif.sh                          # build the wrapper .sif + register as a DataLad container
source ./config.sh && micromamba run -n babs python 03_build_input.py   # build the HCP input dataset
bash 04_run_babs.sh                           # render YAML -> init -> validate 1 subj -> submit rest -> merge
micromamba run -n babs python verify.py ~/babs_hcp/outputs   # QC: confirm 6 valid maps per subject
```

Each `.sh` sources `config.sh` itself; `03_build_input.py` reads the same values from the
environment, so `source ./config.sh` first. It builds the cohort listed in `subjects.txt`
(override with `--subjects 100307,100408`), copying each subject's files into the dataset and
annexing them (MD5E-checksummed, so the input dataset is self-contained, content-verifiable,
and portable). `04_run_babs.sh` renders `qsirecon_hcp.yaml` from the template, validates
`$VALIDATE_SUB` first, then submits the rest, waits, merges, and clones the outputs.

## Local single-node SLURM (note)

BABS targets HPC SLURM clusters; here we run a one-node SLURM on the local machine (node
`gilmore`, partition `compute`). `01_fix_slurm.sh` works around an Intel hybrid-CPU
(i9-14900K) topology quirk that otherwise leaves the node `INVALID_REG`. After it runs,
`sinfo` should show the node `idle`.

## The result is a shareable git-annex dataset

Inputs are versioned in DataLad up front; each subject's output is committed with full
provenance (`datalad containers-run`) and pushed to `project/output_ria` as its job
finishes; `babs merge` consolidates them. To share or retrieve:

```bash
# the processed results
datalad clone "ria+file://$HOME/babs_hcp/project/output_ria#~data" my_outputs
cd my_outputs && datalad get sub-100307_qsirecon-26-0-0.zip

# the HCP inputs (DUA applies)
datalad clone ~/babs_hcp/input_hcp my_hcp_inputs
```

A result zip contains `qsirecon/derivatives/qsirecon-{NODDI,DIPYDKI}/sub-<id>/dwi/*.nii.gz`.
`verify.py` is the QC gate: point it at the result zips or the cloned `outputs/` and it
confirms each subject has all six maps, in MNI space, on the 2 mm grid, with a non-empty
brain and plausible value ranges (exits nonzero on any failure).

## Reproducibility

Everything that determines the outputs is pinned:

- **QSIRecon container** — `pennlinc/qsirecon@sha256:1ae7295e…` (`QSIRECON_IMAGE` in
  `config.sh`). `02_build_sif.sh` builds from the local Docker image if its digest matches,
  otherwise pulls that exact digest from the registry.
- **TemplateFlow** — the MNI152NLin2009cAsym normalization target is **baked into the .sif**
  (`02_build_sif.sh` stages it; the image sets `TEMPLATEFLOW_HOME=/opt/templateflow`), so runs
  are hermetic/offline and immune to upstream template drift — no host cache is bound (client
  version recorded as `TEMPLATEFLOW_CLIENT` in `config.sh`).
- **Registration seed** — `run_hcp.py` sets `ANTS_RANDOM_SEED=1` for the T1w→MNI
  registration. (We do *not* force single-threaded ITK: that gives bit-for-bit reproducibility
  but ~4x slower registration, infeasible for the cohort — so results reproduce within
  tolerance, not bitwise.)
- **Toolchain** (`environment.yml`) — python 3.11, babs 0.5.4, datalad 1.5.0,
  datalad-container 1.2.6, git-annex 10.20260525.
- **Cohort** — the canonical 100 subjects in `subjects.txt`; **inputs** copied + MD5E-checksummed.
- **Output grid** — 2 mm MNI152NLin2009cAsym (`OUTPUT_RESOLUTION` in `maps.py`).
- **Data release** — HCP-YA **S1200** Open Access.

Because results reproduce within tolerance rather than bit-for-bit, the drift check is
**per-voxel**, not a hash: re-run a subject and correlate against its published copy with
`verify.py <fresh> --compare-to <published>` — each map must reach spatial correlation
r ≥ 0.999 (`--corr-threshold`); a changed template / container / tool version drops r below
that. This mirrors how the field checks pipeline stability (voxelwise correlation + difference
maps), and it needs no committed reference — you compare against the Zenodo deposit.

## Adapting to a new dataset

The project separates generic BABS scaffolding from a small dataset-specific surface. To run a
different dataset you should only need to change:

1. **`config.sh`** — paths, `BABS_HCP_INPUT_SRC`, `FS_LICENSE`, `CONTAINER_NAME`,
   `QSIRECON_IMAGE` (digest), zip name/version, SLURM resources, `VALIDATE_SUB`.
2. **Decide whether you even need the wrapper.** It exists only for HCP's quirks (two passes,
   the b ≤ 2000 DKI filter, the bare-numeric `hcpya` layout, tolerating a cosmetic exit-1). For
   a standard *single-pass* run on a BIDS dataset (or QSIPrep derivatives) that exits 0, **drop
   `run_hcp.py` / `Apptainer.def.tmpl`**, register the stock `pennlinc/qsirecon` (or `qsiprep`)
   image directly, and drive it through `bids_app_args` in the YAML — no wrapper at all.
3. **If you keep the wrapper**, set its recon spec(s), `--input-type`, and the bval-filter
   on/off for the new modality.
4. Point `BABS_HCP_INPUT_SRC` at the new data and run `03_build_input.py`.
5. Update `verify.py`'s expected resolution / parameter bounds for the new outputs (the
   `--compare-to` drift check is dataset-agnostic).

## Files

| file | role |
|------|------|
| `config.sh` | **the only file you edit** — all host/dataset-specific values |
| `subjects.txt` | canonical cohort: HCP-YA S1200 subject ids (read by `03_build_input.py`) |
| `00_install_env.sh` | install micromamba + the `babs` environment |
| `environment.yml` | pinned `babs` toolchain (used by `00_install_env.sh`) |
| `01_fix_slurm.sh` | repair the local single-node SLURM (sudo) |
| `02_build_sif.sh` | build the wrapper image and register it with DataLad |
| `03_build_input.py` | assemble the HCP input DataLad dataset |
| `04_run_babs.sh` | run the BABS workflow end to end |
| `qsirecon_hcp.yaml.tmpl` | BABS container-config template (rendered using `config.sh`) |
| `qsirecon_hcp.yaml` | rendered config, generated by `04_run_babs.sh` (git-ignored) |
| `Apptainer.def.tmpl` | wrapper image recipe template (digest-pinned `From:`); `Apptainer.def` is generated by `02_build_sif.sh` (git-ignored) |
| `run_hcp.py` | in-container orchestrator: two passes + bval filter |
| `bval_filter.py` | drop b > 2000 volumes for the DKI pass |
| `maps.py` | the six-map naming contract |
| `noddi_mni.yaml`, `dki_mni.yaml` | QSIRecon recon specs |
| `linear_plugin.yml` | nipype Linear plugin (avoids the hcpya report-node deadlock) |
| `verify.py` | QC gate: plausibility checks + `--compare-to` per-voxel correlation |
| `LICENSE` | MIT (code only; data/outputs under the HCP Open Access DUA) |
