# Calibration V3 — Frozen Panel (eyeball summary)

Generated 2026-07-17T09:28:30.426519+00:00 · seed 20230701 · freeze sha256 `f47725600468f02c…`

## Pool reconciliation

The protocol's committed reference counts reproduce under the LITERAL definitions; the draw then uses documented refinements (in-window bars, early/late overlap→late, data-quality gates, reserve exclusion), giving the smaller draw pools.

| pool | protocol (literal) | reproduced (literal) | draw pool |
|---|---|---|---|
| living | 2142 | 2142 ✓ | 1923 (−reserve −DQ) |
| early-death delisted | 4684 | 4684 ✓ | 1832 (in-window, −overlap 1759, −DQ) |
| late-death delisted | 4179 | 4179 ✓ | 3295 (−DQ) |

## Data-quality gates (pre-registered, applied before cutpoints)

Excluded names by reason: {"penny_median_raw_close": 129, "sentinel_bars": 407, "price_gap_gt_90d": 291, "extreme_jump_bars": 280, "nonpositive_raw_close": 49} — sentinel bars, sub-penny tick-noise, ≥2 extreme (>8×) jumps, >90-day internal holes. These strip ARTIFACTUAL vol before it can set the grid.

## Frozen cutpoints (FIX-5: combined draw pool, reserve-disjoint)

- vol median combined **0.580521** (living-only 0.460893; protocol's earlier live-verified figure was ~0.576 on the literal, un-gated, reserve-included pool — drift is explained by the documented refinements and is refrozen here per §2.3)
- vol p75 combined 0.872776 · tail names in panel: **55** (requirement ≥50: PASS)
- cap tertiles combined: $352,255,250 / $1,783,298,667 (adjc-basis, see cap_basis_note; protocol's earlier figures ~$0.38B/$2.68B used the split-double-counting raw-close basis)

## Panel composition

living 132 · tail_topup 13 · early 33 · late 33 · total 211

### Living cells (cap × vol)

| cell | n | sectors | example names |
|---|---|---|---|
| large_liquid|high | 22 | 10 | ACAD, ADNT, AKAM, ALGN, ANGI, APLS … |
| large_liquid|low | 22 | 11 | AGNC, ARMK, AZO, BCS, BPOP, CABO … |
| mid|high | 22 | 9 | AKBA, BLDR, CARS, CZR, DDD, ENPH … |
| mid|low | 22 | 10 | AX, BKH, CBRL, COKE, CSGP, CUBE … |
| small|high | 22 | 9 | AEYE, AGEN, AUDC, AVTX, CRWS, CTGO … |
| small|low | 22 | 9 | ARKR, BELFA, BMRC, BRID, CHMI, CSPI … |

### Early-death sleeve

| era | vol | symbols |
|---|---|---|
| dotcom_2000_2003 | high | CDTS, CLPA, DGLV, HCDC, PSIXQ |
| dotcom_2000_2003 | low | AK, CBNY1, MEA1, PNWB, SXNB |
| gfc_cycle_2004_2009 | high | AMSI, ENPT1, NETM, RHT1, STEL1 |
| gfc_cycle_2004_2009 | low | ANDW, CLK, DEBS, DYSVY, RSE1, UST1 |
| post_2010 | high | ECTX1, ITIG, LIHR, NAMC, VION, VOXW |
| post_2010 | low | AIPC, AMPH1, BJS, KTII, SY2, ZNT |

### Late-death sleeve

| era | vol | symbols |
|---|---|---|
| y2011_2015 | high | CRTP, HEARQ, SSFC, VTSS, XSELY |
| y2011_2015 | low | ARDNA, ATMI, FBMI, HCBK, ROSE1 |
| y2016_2019 | high | GST, IDSA, MCOX, QTWW, SQNM |
| y2016_2019 | low | ASBB, EQGP, FMER, GMKYY, NYRT, RT |
| y2020_plus | high | BTCM, MLND, ORTX, RYCE, SQ, TGAN |
| y2020_plus | low | BGNE, DLPH, LPT, RBI, UBP, UZA |

### Tail top-up sleeve (FIX-10)

| era | vol | symbols |
|---|---|---|
| dotcom_2000_2003 | high | CMTO, GMGC |
| gfc_cycle_2004_2009 | high | EUROY, TPLQ |
| living | high | ALOY |
| post_2010 | high | FMTIF, FNLYQ |
| y2011_2015 | high | CNVR1, FSNMQ |
| y2016_2019 | high | HSGX, LKCO1 |
| y2020_plus | high | FGEN, WEI |

## OOS reserve (FIX-37, excluded from the draw)

101 resolved; not in warehouse: —

## Flags

- thin sector corner large_liquid|high/Consumer Defensive: 2 eligible
- thin sector corner large_liquid|high/Utilities: 1 eligible
- thin sector corner mid|high/Consumer Defensive: 2 eligible
- thin sector corner mid|high/Utilities: 1 eligible

## Exclusion / replacement log

- DQ exclude ABAT (living): penny_median_raw_close
- DQ exclude ABVC (living): sentinel_bars
- DQ exclude ACB (living): sentinel_bars
- DQ exclude ACIC (living): price_gap_gt_90d
- DQ exclude AG (living): sentinel_bars
- DQ exclude AIFF (living): penny_median_raw_close
- DQ exclude AIMD (living): sentinel_bars
- DQ exclude AKR (living): sentinel_bars
- DQ exclude ALBT (living): sentinel_bars
- DQ exclude ALP (living): sentinel_bars
- DQ exclude ALRS (living): price_gap_gt_90d
- DQ exclude ALT (living): sentinel_bars
- DQ exclude ALTO (living): sentinel_bars
- DQ exclude AMPG (living): penny_median_raw_close
- DQ exclude AMX (living): sentinel_bars
- DQ exclude APLD (living): sentinel_bars
- DQ exclude AREN (living): sentinel_bars
- DQ exclude AROC (living): sentinel_bars
- DQ exclude ARWR (living): sentinel_bars
- DQ exclude ASTH (living): sentinel_bars
- DQ exclude ASTI (living): sentinel_bars
- DQ exclude ATLX (living): sentinel_bars
- DQ exclude ATNM (living): price_gap_gt_90d
- DQ exclude ATON (living): sentinel_bars
- DQ exclude AUGO (living): extreme_jump_bars
- DQ exclude AUPH (living): sentinel_bars
- DQ exclude AYA (living): penny_median_raw_close
- DQ exclude BEEM (living): penny_median_raw_close
- DQ exclude BGSI (living): price_gap_gt_90d
- DQ exclude BINI (living): sentinel_bars
- DQ exclude BIO-B (living): price_gap_gt_90d
- DQ exclude BLFS (living): penny_median_raw_close
- DQ exclude BLNE (living): sentinel_bars
- DQ exclude BLNK (living): extreme_jump_bars
- DQ exclude BMNR (living): sentinel_bars
- DQ exclude BNC (living): penny_median_raw_close
- DQ exclude BRBS (living): sentinel_bars
- DQ exclude BRK-A (living): sentinel_bars
- DQ exclude BRTX (living): sentinel_bars
- DQ exclude BTCS (living): sentinel_bars
- DQ exclude BWEN (living): price_gap_gt_90d
- DQ exclude BYRN (living): penny_median_raw_close
- DQ exclude CAPR (living): sentinel_bars
- DQ exclude CATX (living): sentinel_bars
- DQ exclude CBAT (living): price_gap_gt_90d
- DQ exclude CETY (living): sentinel_bars
- DQ exclude CHAI (living): penny_median_raw_close
- DQ exclude CKX (living): price_gap_gt_90d
- DQ exclude CLRO (living): extreme_jump_bars
- DQ exclude CLSK (living): sentinel_bars
- DQ exclude CMBT (living): price_gap_gt_90d
- DQ exclude CMCL (living): penny_median_raw_close
- DQ exclude CMPX (living): price_gap_gt_90d
- DQ exclude CODA (living): sentinel_bars
- DQ exclude COSM (living): sentinel_bars
- DQ exclude CRVO (living): sentinel_bars
- DQ exclude CSBR (living): sentinel_bars
- DQ exclude CTM (living): sentinel_bars
- DQ exclude CUBI (living): price_gap_gt_90d
- DQ exclude DCTH (living): sentinel_bars
- DQ exclude DFTX (living): sentinel_bars
- DQ exclude DSS (living): sentinel_bars
- DQ exclude DTST (living): penny_median_raw_close
- DQ exclude DYAI (living): price_gap_gt_90d
- DQ exclude EBMT (living): sentinel_bars
- DQ exclude EFOI (living): extreme_jump_bars
- DQ exclude ELBM (living): sentinel_bars
- DQ exclude ENFY (living): sentinel_bars
- DQ exclude EP (living): penny_median_raw_close
- DQ exclude EPM (living): sentinel_bars
- DQ exclude EQX (living): price_gap_gt_90d
- DQ exclude EU (living): sentinel_bars
- DQ exclude FERG (living): price_gap_gt_90d
- DQ exclude FGBI (living): price_gap_gt_90d
- DQ exclude FKWL (living): sentinel_bars
- DQ exclude FNGR (living): sentinel_bars
- DQ exclude FTI (living): sentinel_bars
- DQ exclude FUBO (living): sentinel_bars
- DQ exclude FVCB (living): price_gap_gt_90d
- DQ exclude GDC (living): extreme_jump_bars
- DQ exclude GLXY (living): extreme_jump_bars
- DQ exclude GPRK (living): price_gap_gt_90d
- DQ exclude GPUS (living): penny_median_raw_close
- DQ exclude GTBP (living): sentinel_bars
- DQ exclude GURE (living): sentinel_bars
- DQ exclude GWAV (living): sentinel_bars
- DQ exclude HIVE (living): penny_median_raw_close
- DQ exclude HPAI (living): sentinel_bars
- DQ exclude HYFT (living): sentinel_bars
- DQ exclude IDR (living): penny_median_raw_close
- DQ exclude IGC (living): sentinel_bars
- DQ exclude IHG (living): sentinel_bars
- DQ exclude IMOS (living): sentinel_bars
- DQ exclude IMRN (living): price_gap_gt_90d
- DQ exclude INM (living): penny_median_raw_close
- DQ exclude INNV (living): sentinel_bars
- DQ exclude INSG (living): sentinel_bars
- DQ exclude IPDN (living): price_gap_gt_90d
- DQ exclude IRD (living): sentinel_bars
- DQ exclude ITRG (living): sentinel_bars
- DQ exclude IVT (living): sentinel_bars
- DQ exclude KAVL (living): sentinel_bars
- DQ exclude KINS (living): extreme_jump_bars
- DQ exclude KMDA (living): price_gap_gt_90d
- DQ exclude KNDI (living): price_gap_gt_90d
- DQ exclude KNTK (living): sentinel_bars
- DQ exclude KRMD (living): penny_median_raw_close
- DQ exclude LCTX (living): price_gap_gt_90d
- DQ exclude LFMD (living): penny_median_raw_close
- DQ exclude LFVN (living): sentinel_bars
- DQ exclude LINK (living): sentinel_bars
- DQ exclude LIVE (living): sentinel_bars
- DQ exclude LMNR (living): price_gap_gt_90d
- DQ exclude LODE (living): sentinel_bars
- DQ exclude LSAK (living): price_gap_gt_90d
- DQ exclude LWLG (living): price_gap_gt_90d
- DQ exclude MDXG (living): price_gap_gt_90d
- DQ exclude MESO (living): sentinel_bars
- DQ exclude MIGI (living): price_gap_gt_90d
- DQ exclude MKC-V (living): sentinel_bars
- DQ exclude MRNFF (living): price_gap_gt_90d
- DQ exclude MRVL (living): sentinel_bars
- DQ exclude MTA (living): sentinel_bars
- DQ exclude MVBF (living): sentinel_bars
- DQ exclude NATR (living): price_gap_gt_90d
- DQ exclude NB (living): penny_median_raw_close
- DQ exclude NCPL (living): sentinel_bars
- DQ exclude NDRA (living): penny_median_raw_close
- DQ exclude NEO (living): sentinel_bars
- DQ exclude NIXX (living): sentinel_bars
- DQ exclude NNVC (living): sentinel_bars
- DQ exclude NTB (living): price_gap_gt_90d
- DQ exclude NTIP (living): price_gap_gt_90d
- DQ exclude NTRP (living): sentinel_bars
- DQ exclude NUTX (living): sentinel_bars
- DQ exclude NUWE (living): sentinel_bars
- DQ exclude NVOS (living): sentinel_bars
- DQ exclude OBK (living): price_gap_gt_90d
- DQ exclude OBT (living): sentinel_bars
- DQ exclude ODV (living): sentinel_bars
- DQ exclude OGI (living): sentinel_bars
- DQ exclude OPRX (living): sentinel_bars
- DQ exclude ORLA (living): sentinel_bars
- DQ exclude ORMP (living): price_gap_gt_90d
- DQ exclude PAYS (living): sentinel_bars
- DQ exclude AAWHQ (early): sentinel_bars
- DQ exclude ABDS (early): sentinel_bars
- DQ exclude ABFIQ (early): sentinel_bars
- DQ exclude ABIZA (early): extreme_jump_bars
- DQ exclude ABRX (early): sentinel_bars
- DQ exclude ABWTQ (early): sentinel_bars
- DQ exclude ACDO (early): price_gap_gt_90d
- DQ exclude ADELQ (early): penny_median_raw_close
- DQ exclude ADIC (early): price_gap_gt_90d
- DQ exclude ADRX (early): price_gap_gt_90d
- DQ exclude AJL (early): price_gap_gt_90d
- DQ exclude AKLM (early): price_gap_gt_90d
- DQ exclude ALLP (early): sentinel_bars
- DQ exclude AMIIQ (early): penny_median_raw_close
- DQ exclude ANCC (early): sentinel_bars
- DQ exclude APCC (early): penny_median_raw_close
- DQ exclude ASPXQ (early): sentinel_bars
- DQ exclude ATISZ (early): penny_median_raw_close
- DQ exclude AVDO (early): penny_median_raw_close
- DQ exclude AYS (early): price_gap_gt_90d
- DQ exclude BDGPA (early): sentinel_bars
- DQ exclude BDLN (early): extreme_jump_bars
- DQ exclude BEOSZ (early): penny_median_raw_close
- DQ exclude BGST (early): penny_median_raw_close
- DQ exclude BPURQ (early): sentinel_bars
- DQ exclude BREK (early): penny_median_raw_close
- DQ exclude BS (early): sentinel_bars
- DQ exclude CALGZ (early): sentinel_bars
- DQ exclude CDD (early): price_gap_gt_90d
- DQ exclude CES (early): penny_median_raw_close
- DQ exclude CJHBQ (early): sentinel_bars
- DQ exclude CLIC (early): penny_median_raw_close
- DQ exclude COPIQ (early): penny_median_raw_close
- DQ exclude DANKY (early): sentinel_bars
- DQ exclude DATC (early): sentinel_bars
- DQ exclude DCNAQ (early): sentinel_bars
- DQ exclude DFCLQ (early): sentinel_bars
- DQ exclude DSLN (early): penny_median_raw_close
- DQ exclude EGLE1 (early): sentinel_bars
- DQ exclude EGR (early): price_gap_gt_90d
- DQ exclude ENRNQ (early): penny_median_raw_close
- DQ exclude EPIX1 (early): sentinel_bars
- DQ exclude EPYSQ (early): sentinel_bars
- DQ exclude ERB (early): price_gap_gt_90d
- DQ exclude ESCI (early): sentinel_bars
- DQ exclude EUA (early): penny_median_raw_close
- DQ exclude FASH (early): penny_median_raw_close
- DQ exclude FJCC (early): sentinel_bars
- DQ exclude FLMIQ (early): sentinel_bars
- DQ exclude FMXLQ (early): sentinel_bars
- DQ exclude FNT (early): penny_median_raw_close
- DQ exclude GBIXQ (early): sentinel_bars
- DQ exclude GBUR (early): penny_median_raw_close
- DQ exclude GENUQ (early): sentinel_bars
- DQ exclude GHVIQ (early): penny_median_raw_close
- DQ exclude GLGSQ (early): sentinel_bars
- DQ exclude HORT (early): sentinel_bars
- DQ exclude HOTJ (early): price_gap_gt_90d
- DQ exclude HSE (early): price_gap_gt_90d
- DQ exclude IDPIQ (early): sentinel_bars
- DQ exclude IDWK (early): penny_median_raw_close
- DQ exclude IMPV1 (early): penny_median_raw_close
- DQ exclude INAGY (early): penny_median_raw_close
- DQ exclude INSGY (early): penny_median_raw_close
- DQ exclude IPRT (early): penny_median_raw_close
- DQ exclude ISOOQ (early): sentinel_bars
- DQ exclude JM (early): price_gap_gt_90d
- DQ exclude JMAR (early): sentinel_bars
- DQ exclude KLUCQ (early): penny_median_raw_close
- DQ exclude KMAGQ (early): sentinel_bars
- DQ exclude LIPD (early): sentinel_bars
- DQ exclude LOCK1 (early): sentinel_bars
- DQ exclude MAIY (early): penny_median_raw_close
- DQ exclude MAXIQ (early): sentinel_bars
- DQ exclude MDIZQ (early): extreme_jump_bars
- DQ exclude MHUT (early): extreme_jump_bars
- DQ exclude MNYG (early): penny_median_raw_close
- DQ exclude MOVIQ (early): sentinel_bars
- DQ exclude MTIC (early): sentinel_bars
- DQ exclude MXUS (early): sentinel_bars
- DQ exclude NASMQ (early): sentinel_bars
- DQ exclude NCDI (early): penny_median_raw_close
- DQ exclude NCNXQ (early): extreme_jump_bars
- DQ exclude NCTI (early): penny_median_raw_close
- DQ exclude NSCT (early): penny_median_raw_close
- DQ exclude NSO (early): penny_median_raw_close
- DQ exclude NTBKQ (early): sentinel_bars
- DQ exclude NTEC1 (early): sentinel_bars
- DQ exclude NTIQ (early): price_gap_gt_90d
- DQ exclude NWAC (early): sentinel_bars
- DQ exclude OFIS (early): penny_median_raw_close
- DQ exclude PHYCQ (early): sentinel_bars
- DQ exclude PRVOZ (early): penny_median_raw_close
- DQ exclude PSITY (early): sentinel_bars
- DQ exclude RDOC (early): penny_median_raw_close
- DQ exclude RDRTQ (early): sentinel_bars
- DQ exclude RGIDQ (early): sentinel_bars
- DQ exclude RHDCQ (early): sentinel_bars
- DQ exclude RTPRQ (early): sentinel_bars
- DQ exclude SCRA (early): sentinel_bars
- DQ exclude SEEC (early): penny_median_raw_close
- DQ exclude SEMI1 (early): sentinel_bars
- DQ exclude SIDE (early): price_gap_gt_90d
- DQ exclude SLW (early): price_gap_gt_90d
- DQ exclude SMDK (early): penny_median_raw_close
- DQ exclude SNETE (early): penny_median_raw_close
- DQ exclude SPPTQ (early): extreme_jump_bars
- DQ exclude TARR (early): sentinel_bars
- DQ exclude TCK (early): price_gap_gt_90d
- DQ exclude TENF (early): penny_median_raw_close
- DQ exclude TSTN (early): penny_median_raw_close
- DQ exclude TVINQ (early): sentinel_bars
- DQ exclude TWTV (early): penny_median_raw_close
- DQ exclude UC (early): penny_median_raw_close
- DQ exclude UCMPQ (early): penny_median_raw_close
- DQ exclude UNRMY (early): extreme_jump_bars
- DQ exclude UPHN (early): sentinel_bars
- DQ exclude UPSL (early): sentinel_bars
- DQ exclude URB (early): price_gap_gt_90d
- DQ exclude URSI (early): penny_median_raw_close
- DQ exclude USEY (early): sentinel_bars
- DQ exclude VCAT (early): penny_median_raw_close
- DQ exclude VRAI1 (early): sentinel_bars
- DQ exclude WN (early): price_gap_gt_90d
- DQ exclude WSPTQ (early): sentinel_bars
- DQ exclude WVWCQ (early): sentinel_bars
- DQ exclude YBTVQ (early): sentinel_bars
- DQ exclude ABCM (late): nonpositive_raw_close
- DQ exclude ABF (late): extreme_jump_bars
- DQ exclude ABK (late): penny_median_raw_close
- DQ exclude ABST (late): price_gap_gt_90d
- DQ exclude ABWG (late): sentinel_bars
- DQ exclude ACF (late): extreme_jump_bars
- DQ exclude ACL (late): price_gap_gt_90d
- DQ exclude ACRX (late): extreme_jump_bars
- DQ exclude ACS (late): extreme_jump_bars
- DQ exclude ADD (late): sentinel_bars
- DQ exclude ADMP (late): extreme_jump_bars
- DQ exclude ADPI (late): price_gap_gt_90d
- DQ exclude AEA (late): extreme_jump_bars
- DQ exclude AENZ (late): nonpositive_raw_close
- DQ exclude AEY (late): extreme_jump_bars
- DQ exclude AEZ (late): sentinel_bars
- DQ exclude AFFI (late): sentinel_bars
- DQ exclude AFX (late): price_gap_gt_90d
- DQ exclude AHP (late): extreme_jump_bars
- DQ exclude AICIQ (late): sentinel_bars
- DQ exclude AIJ (late): sentinel_bars
- DQ exclude AINN (late): extreme_jump_bars
- DQ exclude AIPT (late): extreme_jump_bars
- DQ exclude AKER (late): sentinel_bars
- DQ exclude ALBO (late): extreme_jump_bars
- DQ exclude ALCS (late): sentinel_bars
- DQ exclude ALQA (late): extreme_jump_bars
- DQ exclude ALR (late): extreme_jump_bars
- DQ exclude ALU (late): price_gap_gt_90d
- DQ exclude ALXA (late): extreme_jump_bars
- DQ exclude AMBTQ (late): sentinel_bars
- DQ exclude AMIEQ (late): sentinel_bars
- DQ exclude AMRH (late): sentinel_bars
- DQ exclude AMRS (late): extreme_jump_bars
- DQ exclude ANE (late): price_gap_gt_90d
- DQ exclude ANG (late): nonpositive_raw_close
- DQ exclude ANRZ (late): sentinel_bars
- DQ exclude AOG (late): price_gap_gt_90d
- DQ exclude APCS (late): penny_median_raw_close
- DQ exclude APK (late): extreme_jump_bars
- DQ exclude APL (late): price_gap_gt_90d
- DQ exclude APTI (late): price_gap_gt_90d
- DQ exclude APW (late): penny_median_raw_close
- DQ exclude AQNA (late): nonpositive_raw_close
- DQ exclude AQXP (late): extreme_jump_bars
- DQ exclude ARCE (late): nonpositive_raw_close
- DQ exclude ARCH (late): extreme_jump_bars
- DQ exclude ARGO (late): nonpositive_raw_close
- DQ exclude ARJ (late): sentinel_bars
- DQ exclude ARNA (late): extreme_jump_bars
- DQ exclude ARPO (late): price_gap_gt_90d
- DQ exclude ARRW (late): price_gap_gt_90d
- DQ exclude ARV (late): extreme_jump_bars
- DQ exclude ASAL (late): sentinel_bars
- DQ exclude ASCX (late): price_gap_gt_90d
- DQ exclude ASGR (late): price_gap_gt_90d
- DQ exclude ASYT (late): sentinel_bars
- DQ exclude ATB (late): price_gap_gt_90d
- DQ exclude ATH (late): price_gap_gt_90d
- DQ exclude ATHYQ (late): sentinel_bars
- DQ exclude ATN (late): extreme_jump_bars
- DQ exclude ATNF (late): sentinel_bars
- DQ exclude ATNX (late): sentinel_bars
- DQ exclude ATT (late): sentinel_bars
- DQ exclude ATTO (late): sentinel_bars
- DQ exclude ATU (late): extreme_jump_bars
- DQ exclude ATX (late): extreme_jump_bars
- DQ exclude AUD (late): price_gap_gt_90d
- DQ exclude AUTN (late): price_gap_gt_90d
- DQ exclude AUY (late): extreme_jump_bars
- DQ exclude AVCO (late): extreme_jump_bars
- DQ exclude AVE (late): penny_median_raw_close
- DQ exclude AWEB (late): sentinel_bars
- DQ exclude AXH (late): extreme_jump_bars
- DQ exclude AYD (late): extreme_jump_bars
- DQ exclude BABY (late): extreme_jump_bars
- DQ exclude BAC-WS-B (late): sentinel_bars
- DQ exclude BAGR (late): extreme_jump_bars
- DQ exclude BAS (late): extreme_jump_bars
- DQ exclude BBA (late): extreme_jump_bars
- DQ exclude BBCZ (late): sentinel_bars
- DQ exclude BBR (late): extreme_jump_bars
- DQ exclude BCF (late): price_gap_gt_90d
- DQ exclude BCONQ (late): sentinel_bars
- DQ exclude BEC (late): price_gap_gt_90d
- DQ exclude BED (late): extreme_jump_bars
- DQ exclude BFD (late): sentinel_bars
- DQ exclude BGEN (late): price_gap_gt_90d
- DQ exclude BIOA-WS (late): penny_median_raw_close
- DQ exclude BIOC (late): sentinel_bars
- DQ exclude BIR (late): extreme_jump_bars
- DQ exclude BJCT (late): sentinel_bars
- DQ exclude BKUNA (late): sentinel_bars
- DQ exclude BLC (late): extreme_jump_bars
- DQ exclude BMW (late): sentinel_bars
- DQ exclude BOMN (late): price_gap_gt_90d
- DQ exclude BOP (late): extreme_jump_bars
- DQ exclude BOY (late): extreme_jump_bars
- DQ exclude BPMX (late): penny_median_raw_close
- DQ exclude BPZRQ (late): sentinel_bars
- DQ exclude BRE (late): extreme_jump_bars
- DQ exclude BRK (late): extreme_jump_bars
- DQ exclude BRP (late): price_gap_gt_90d
- DQ exclude BSG (late): price_gap_gt_90d
- DQ exclude BSPE (late): sentinel_bars
- DQ exclude BSQR (late): nonpositive_raw_close
- DQ exclude BTL (late): extreme_jump_bars
- DQ exclude BTWNU (late): nonpositive_raw_close
- DQ exclude BUCY (late): sentinel_bars
- DQ exclude BURG (late): extreme_jump_bars
- DQ exclude BVB (late): extreme_jump_bars
- DQ exclude BVH (late): extreme_jump_bars
- DQ exclude BWEBF (late): sentinel_bars
- DQ exclude BWN (late): extreme_jump_bars
- DQ exclude BWNG (late): price_gap_gt_90d
- DQ exclude BWTR (late): sentinel_bars
- DQ exclude BXE (late): penny_median_raw_close
- DQ exclude BXRX (late): extreme_jump_bars
- DQ exclude BYH (late): sentinel_bars
- DQ exclude C-WS-A (late): sentinel_bars
- DQ exclude CAA (late): extreme_jump_bars
- DQ exclude CABL (late): extreme_jump_bars
- DQ exclude CALAQ (late): sentinel_bars
- DQ exclude CALCQ (late): sentinel_bars
- DQ exclude CALL (late): extreme_jump_bars
- DQ exclude CALL1 (late): sentinel_bars
- DQ exclude CAMH (late): sentinel_bars
- DQ exclude CANOQ (late): sentinel_bars
- DQ exclude CATP (late): price_gap_gt_90d
- DQ exclude CAV (late): price_gap_gt_90d
- DQ exclude CBA (late): price_gap_gt_90d
- DQ exclude CBAK (late): extreme_jump_bars
- DQ exclude CBE (late): sentinel_bars
- DQ exclude CBMC (late): sentinel_bars
- DQ exclude CBMX (late): extreme_jump_bars
- DQ exclude CBNR (late): sentinel_bars
- DQ exclude CBX (late): penny_median_raw_close
- DQ exclude CCBL (late): price_gap_gt_90d
- DQ exclude CCBN (late): price_gap_gt_90d
- DQ exclude CCCL (late): extreme_jump_bars
- DQ exclude CCIH (late): price_gap_gt_90d
- DQ exclude CCME (late): extreme_jump_bars
- DQ exclude CCTYQ (late): sentinel_bars
- DQ exclude CCV (late): nonpositive_raw_close
- DQ exclude CDG (late): sentinel_bars
- DQ exclude CDIC (late): extreme_jump_bars
- DQ exclude CDO (late): price_gap_gt_90d
- DQ exclude CEA (late): price_gap_gt_90d
- DQ exclude CEBC (late): price_gap_gt_90d
- DQ exclude CEC (late): price_gap_gt_90d
- DQ exclude CELM (late): penny_median_raw_close
- DQ exclude CEO (late): extreme_jump_bars
- DQ exclude CEQP (late): nonpositive_raw_close
- DQ exclude CFC (late): extreme_jump_bars
- DQ exclude CFCP (late): extreme_jump_bars
- DQ exclude CFIVU (late): nonpositive_raw_close
- DQ exclude CFRX (late): sentinel_bars
- DQ exclude CGE (late): extreme_jump_bars
- DQ exclude CGP (late): extreme_jump_bars
- DQ exclude CGR (late): price_gap_gt_90d
- DQ exclude CGRN (late): extreme_jump_bars
- DQ exclude CHAS (late): extreme_jump_bars
- DQ exclude CHG (late): price_gap_gt_90d
- DQ exclude CHRT (late): price_gap_gt_90d
- DQ exclude CHZS (late): penny_median_raw_close
- DQ exclude CIDM (late): extreme_jump_bars
- DQ exclude CIN (late): extreme_jump_bars
- DQ exclude CIR (late): nonpositive_raw_close
- DQ exclude CJT (late): sentinel_bars
- DQ exclude CK (late): extreme_jump_bars
- DQ exclude CLDN (late): price_gap_gt_90d
- DQ exclude CLE (late): extreme_jump_bars
- DQ exclude CLNC (late): price_gap_gt_90d
- DQ exclude CLNT (late): price_gap_gt_90d
- DQ exclude CLSN (late): penny_median_raw_close
- DQ exclude CMED (late): price_gap_gt_90d
- DQ exclude CMH (late): extreme_jump_bars
- DQ exclude CMII (late): sentinel_bars
- DQ exclude CMLT (late): penny_median_raw_close
- DQ exclude CMM (late): extreme_jump_bars
- DQ exclude CMPC (late): sentinel_bars
- DQ exclude CNAC (late): extreme_jump_bars
- DQ exclude CNE (late): extreme_jump_bars
- DQ exclude CNG (late): extreme_jump_bars
- DQ exclude CNLG (late): sentinel_bars
- DQ exclude CNST (late): extreme_jump_bars
- DQ exclude CNST1 (late): sentinel_bars
- DQ exclude CNYD (late): extreme_jump_bars
- DQ exclude COH (late): price_gap_gt_90d
- DQ exclude COOPQ (late): sentinel_bars
- DQ exclude CORSQ (late): sentinel_bars
- DQ exclude COSI (late): sentinel_bars
- DQ exclude COX (late): sentinel_bars
- DQ exclude CPC (late): penny_median_raw_close
- DQ exclude CPJ (late): price_gap_gt_90d
- DQ exclude CPN (late): price_gap_gt_90d
- DQ exclude CPU (late): price_gap_gt_90d
- DQ exclude CRA (late): price_gap_gt_90d
- DQ exclude CRG (late): extreme_jump_bars
- DQ exclude CRGEQ (late): sentinel_bars
- DQ exclude CRTX (late): price_gap_gt_90d
- DQ exclude CSCW (late): extreme_jump_bars
- DQ exclude CSKI (late): penny_median_raw_close
- DQ exclude CTQ (late): price_gap_gt_90d
- DQ exclude CTX (late): price_gap_gt_90d
- DQ exclude CTZN (late): sentinel_bars
- DQ exclude CVCY (late): extreme_jump_bars
- DQ exclude CVLB (late): penny_median_raw_close
- DQ exclude CVVT (late): sentinel_bars
- DQ exclude CWG (late): price_gap_gt_90d
- DQ exclude CWN (late): extreme_jump_bars
- DQ exclude CWP (late): extreme_jump_bars
- DQ exclude CXDC (late): extreme_jump_bars
- DQ exclude CXR (late): extreme_jump_bars
- DQ exclude CXS (late): price_gap_gt_90d
- DQ exclude CYNA (late): extreme_jump_bars
- DQ exclude CYRN (late): extreme_jump_bars
- DQ exclude CZOO (late): sentinel_bars
- DQ exclude DAB (late): price_gap_gt_90d
- DQ exclude DARA (late): sentinel_bars
- DQ exclude DATA (late): price_gap_gt_90d
- DQ exclude DB-R (late): sentinel_bars
- DQ exclude DB-R-W (late): sentinel_bars
- DQ exclude DCPH (late): extreme_jump_bars
- DQ exclude DDDC (late): penny_median_raw_close
- DQ exclude DEAR (late): sentinel_bars
- DQ exclude DEP (late): extreme_jump_bars
- DQ exclude DESCQ (late): sentinel_bars
- DQ exclude DFBG (late): price_gap_gt_90d
- DQ exclude DFFN (late): sentinel_bars
- DQ exclude DGSE (late): extreme_jump_bars
- DQ exclude DGWIY (late): penny_median_raw_close
- DQ exclude DLI (late): price_gap_gt_90d
- DQ exclude DLM (late): price_gap_gt_90d
- DQ exclude DMC (late): sentinel_bars
- DQ exclude DMD (late): price_gap_gt_90d
- DQ exclude DME (late): penny_median_raw_close
- DQ exclude DML (late): sentinel_bars
- DQ exclude DOOR (late): price_gap_gt_90d
- DQ exclude DPAC (late): penny_median_raw_close
- DQ exclude DPM (late): extreme_jump_bars
- DQ exclude DRJ (late): penny_median_raw_close
- DQ exclude DRL (late): extreme_jump_bars
- DQ exclude DRP (late): price_gap_gt_90d
- DQ exclude DRX (late): extreme_jump_bars
- DQ exclude DTY (late): extreme_jump_bars
- DQ exclude DUNEU (late): nonpositive_raw_close
- DQ exclude DVIXQ (late): sentinel_bars
- DQ exclude DXMMQ (late): sentinel_bars
- DQ exclude DYNP (late): sentinel_bars
- DQ exclude EAS (late): sentinel_bars
- DQ exclude EBIX (late): extreme_jump_bars
- DQ exclude EBRB (late): price_gap_gt_90d
- DQ exclude ECHO (late): price_gap_gt_90d
- DQ exclude ECT (late): extreme_jump_bars
- DQ exclude ECTYQ (late): sentinel_bars
- DQ exclude EDO (late): sentinel_bars
- DQ exclude EGI (late): extreme_jump_bars
- DQ exclude EGLT (late): extreme_jump_bars
- DQ exclude EGLTQ (late): sentinel_bars
- DQ exclude EKT (late): price_gap_gt_90d
- DQ exclude ELI (late): extreme_jump_bars
- DQ exclude ENGL (late): price_gap_gt_90d
- DQ exclude ENP (late): sentinel_bars
- DQ exclude ENQ (late): extreme_jump_bars
- DQ exclude ENVI (late): price_gap_gt_90d
- DQ exclude EROS (late): price_gap_gt_90d
- DQ exclude ESF (late): extreme_jump_bars
- DQ exclude ESGC (late): extreme_jump_bars
- DQ exclude ESIMF (late): sentinel_bars
- DQ exclude ESSA (late): extreme_jump_bars
- DQ exclude ESTE (late): nonpositive_raw_close
- DQ exclude ETE (late): price_gap_gt_90d
- DQ exclude ETL (late): price_gap_gt_90d
- DQ exclude EVSI (late): penny_median_raw_close
- DQ exclude EVSNF (late): penny_median_raw_close
- DQ exclude EXO (late): sentinel_bars
- DQ exclude EYES (late): extreme_jump_bars
- DQ exclude FAL (late): extreme_jump_bars
- DQ exclude FBC (late): extreme_jump_bars
- DQ exclude FBF (late): penny_median_raw_close
- DQ exclude FBNK (late): extreme_jump_bars
- DQ exclude FBTXQ (late): sentinel_bars
- DQ exclude FCAU (late): price_gap_gt_90d
- DQ exclude FCCY (late): price_gap_gt_90d
- DQ exclude FCSC (late): extreme_jump_bars
- DQ exclude FEES (late): penny_median_raw_close
- DQ exclude FFH (late): extreme_jump_bars
- DQ exclude FFI (late): price_gap_gt_90d
- DQ exclude FH (late): extreme_jump_bars
- DQ exclude FHR (late): price_gap_gt_90d
- DQ exclude FIN (late): sentinel_bars
- DQ exclude FIT (late): price_gap_gt_90d
- DQ exclude FLA (late): extreme_jump_bars
- DQ exclude FLB (late): price_gap_gt_90d
- DQ exclude FMI (late): price_gap_gt_90d
- DQ exclude FNCX (late): sentinel_bars
- DQ exclude FNHC (late): sentinel_bars
- DQ exclude FNJN (late): sentinel_bars
- DQ exclude FOOT (late): price_gap_gt_90d
- DQ exclude FORBQ (late): sentinel_bars
- DQ exclude FORG (late): price_gap_gt_90d
- DQ exclude FOX1 (late): price_gap_gt_90d
- DQ exclude FPC (late): price_gap_gt_90d
- DQ exclude FPFCQ (late): sentinel_bars
- DQ exclude FPFX (late): penny_median_raw_close
- DQ exclude FREQ (late): nonpositive_raw_close
- DQ exclude FRGBQ (late): sentinel_bars
- DQ exclude FRGI (late): nonpositive_raw_close
- DQ exclude FRTL (late): price_gap_gt_90d
- DQ exclude FSIN (late): sentinel_bars
- DQ exclude FTO (late): price_gap_gt_90d
- DQ exclude FTUSQ (late): sentinel_bars
- DQ exclude FVE (late): extreme_jump_bars
- DQ exclude FWM (late): sentinel_bars
- DQ exclude GBP (late): price_gap_gt_90d
- DQ exclude GBT (late): price_gap_gt_90d
- DQ exclude GDN (late): sentinel_bars
- DQ exclude GDW (late): sentinel_bars
- DQ exclude GEC (late): price_gap_gt_90d
- DQ exclude GEPT (late): sentinel_bars
- DQ exclude GGLR (late): sentinel_bars
- DQ exclude GIG-U (late): extreme_jump_bars
- DQ exclude GIG-WS (late): extreme_jump_bars
- DQ exclude GIX-U (late): sentinel_bars
- DQ exclude GIX-UN (late): sentinel_bars
- DQ exclude GIX-WS (late): sentinel_bars
- DQ exclude GLG (late): price_gap_gt_90d
- DQ exclude GLH (late): penny_median_raw_close
- DQ exclude GLPG (late): price_gap_gt_90d
- DQ exclude GMAN1 (late): sentinel_bars
- DQ exclude GMP (late): price_gap_gt_90d
- DQ exclude GMVD (late): extreme_jump_bars
- DQ exclude GNCA (late): sentinel_bars
- DQ exclude GND (late): extreme_jump_bars
- DQ exclude GNTY (late): price_gap_gt_90d
- DQ exclude GNUS (late): extreme_jump_bars
- DQ exclude GNVC (late): extreme_jump_bars
- DQ exclude GORX (late): sentinel_bars
- DQ exclude GRB (late): extreme_jump_bars
- DQ exclude GRYP (late): sentinel_bars
- DQ exclude GTAX (late): penny_median_raw_close
- DQ exclude GTK (late): extreme_jump_bars
- DQ exclude GTT (late): price_gap_gt_90d
- DQ exclude GVE (late): sentinel_bars
- DQ exclude GVP (late): extreme_jump_bars
- DQ exclude GX (late): penny_median_raw_close
- DQ exclude HAC (late): sentinel_bars
- DQ exclude HAI (late): price_gap_gt_90d
- DQ exclude HBG (late): price_gap_gt_90d
- DQ exclude HBM-WS (late): sentinel_bars
- DQ exclude HCCI (late): nonpositive_raw_close
- DQ exclude HCD (late): price_gap_gt_90d
- DQ exclude HCFT (late): extreme_jump_bars
- DQ exclude HDLM (late): sentinel_bars
- DQ exclude HEDYY (late): extreme_jump_bars
- DQ exclude HEIIQ (late): sentinel_bars
- DQ exclude HEP (late): nonpositive_raw_close
- DQ exclude HH (late): extreme_jump_bars
- DQ exclude HIH (late): price_gap_gt_90d
- DQ exclude HK (late): extreme_jump_bars
- DQ exclude HKT (late): extreme_jump_bars
- DQ exclude HLBZ (late): sentinel_bars
- DQ exclude HMB (late): extreme_jump_bars
- DQ exclude HMK (late): sentinel_bars
- DQ exclude HNIN (late): sentinel_bars
- DQ exclude HOME (late): price_gap_gt_90d
- DQ exclude HPC (late): extreme_jump_bars
- DQ exclude HPHW (late): sentinel_bars
- DQ exclude HRH (late): penny_median_raw_close
- DQ exclude HRVEQ (late): sentinel_bars
- DQ exclude HSH (late): price_gap_gt_90d
- DQ exclude HSR (late): sentinel_bars
- DQ exclude HT (late): nonpositive_raw_close
- DQ exclude HTE (late): extreme_jump_bars
- DQ exclude HTG (late): price_gap_gt_90d
- DQ exclude HTV (late): extreme_jump_bars
- DQ exclude HUD (late): extreme_jump_bars
- DQ exclude HUG (late): extreme_jump_bars
- DQ exclude HUMANSOFT (late): price_gap_gt_90d
- DQ exclude HWFGQ (late): sentinel_bars
- DQ exclude HWL (late): price_gap_gt_90d
- DQ exclude HYDGQ (late): sentinel_bars
- DQ exclude HYPRQ (late): sentinel_bars
- DQ exclude IACH (late): extreme_jump_bars
- DQ exclude IAIC (late): penny_median_raw_close
- DQ exclude IBLTZ (late): penny_median_raw_close
- DQ exclude IBNKQ (late): sentinel_bars
- DQ exclude ICOPQ (late): sentinel_bars
- DQ exclude ICPT (late): nonpositive_raw_close
- DQ exclude ICT (late): extreme_jump_bars
- DQ exclude IFT (late): price_gap_gt_90d
- DQ exclude IGOI (late): extreme_jump_bars
- DQ exclude IHR (late): extreme_jump_bars
- DQ exclude IISX (late): sentinel_bars
- DQ exclude ILA (late): extreme_jump_bars
- DQ exclude IMBI (late): sentinel_bars
- DQ exclude IMMCQ (late): sentinel_bars
- DQ exclude IMMY (late): extreme_jump_bars
- DQ exclude IMPCQ (late): sentinel_bars
- DQ exclude IMV (late): extreme_jump_bars
- DQ exclude INB (late): price_gap_gt_90d
- DQ exclude INDU (late): extreme_jump_bars
- DQ exclude INFI (late): sentinel_bars
- DQ exclude INFIQ (late): sentinel_bars
- DQ exclude INPX (late): sentinel_bars
- DQ exclude INVO (late): sentinel_bars
- DQ exclude IO (late): extreme_jump_bars
- DQ exclude IOM (late): extreme_jump_bars
- DQ exclude IOMT (late): sentinel_bars
- DQ exclude IPA (late): sentinel_bars
- DQ exclude IPCI (late): extreme_jump_bars
- DQ exclude IPL (late): extreme_jump_bars
- DQ exclude IRNT (late): sentinel_bars
- DQ exclude ISA (late): extreme_jump_bars
- DQ exclude ISEE1 (late): penny_median_raw_close
- DQ exclude ITCL (late): extreme_jump_bars
- DQ exclude IWA (late): price_gap_gt_90d
- DQ exclude JAV (late): sentinel_bars
- DQ exclude JCTCF (late): extreme_jump_bars
- DQ exclude JDN (late): price_gap_gt_90d
- DQ exclude JE (late): extreme_jump_bars
- DQ exclude JET (late): extreme_jump_bars
- DQ exclude JH (late): extreme_jump_bars
- DQ exclude JOS (late): sentinel_bars
- DQ exclude JPR (late): extreme_jump_bars
- DQ exclude JRJC (late): extreme_jump_bars
- DQ exclude KBL (late): sentinel_bars
- DQ exclude KCAP (late): price_gap_gt_90d
- DQ exclude KCS (late): price_gap_gt_90d
- DQ exclude KDC (late): price_gap_gt_90d
- DQ exclude KEA (late): price_gap_gt_90d
- DQ exclude KED (late): price_gap_gt_90d
- DQ exclude KEG (late): extreme_jump_bars
- DQ exclude KENT (late): price_gap_gt_90d
- DQ exclude KES (late): penny_median_raw_close
- DQ exclude KEYW (late): price_gap_gt_90d
- DQ exclude KFX (late): price_gap_gt_90d
- DQ exclude KMPH (late): extreme_jump_bars
- DQ exclude KNT (late): price_gap_gt_90d
- DQ exclude KONE (late): penny_median_raw_close
- DQ exclude KQIPQ (late): sentinel_bars
- DQ exclude KRB (late): penny_median_raw_close
- DQ exclude KRI (late): extreme_jump_bars
- DQ exclude KSE (late): price_gap_gt_90d
- DQ exclude KTR (late): penny_median_raw_close
- DQ exclude KWKAQ (late): sentinel_bars
- DQ exclude LAAC (late): penny_median_raw_close
- DQ exclude LAF (late): price_gap_gt_90d
- DQ exclude LAIX (late): extreme_jump_bars
- DQ exclude LAN (late): sentinel_bars
- DQ exclude LCE (late): penny_median_raw_close
- DQ exclude LDG (late): price_gap_gt_90d
- DQ exclude LEAF (late): extreme_jump_bars
- DQ exclude LFG (late): nonpositive_raw_close
- DQ exclude LFTC (late): sentinel_bars
- DQ exclude LGC-U (late): extreme_jump_bars
- DQ exclude LGF (late): extreme_jump_bars
- DQ exclude LHN (late): price_gap_gt_90d
- DQ exclude LJPC (late): sentinel_bars
- DQ exclude LJPC1 (late): sentinel_bars
- DQ exclude LK (late): penny_median_raw_close
- DQ exclude LLEXQ (late): extreme_jump_bars
- DQ exclude LMS (late): price_gap_gt_90d
- DQ exclude LNR (late): sentinel_bars
- DQ exclude LOCM (late): sentinel_bars
- DQ exclude LPHI (late): sentinel_bars
- DQ exclude LPI (late): extreme_jump_bars
- DQ exclude LRI (late): extreme_jump_bars
- DQ exclude LVC (late): price_gap_gt_90d
- DQ exclude MADGQ (late): sentinel_bars
- DQ exclude MAH (late): penny_median_raw_close
- DQ exclude MAJR (late): extreme_jump_bars
- DQ exclude MAL (late): price_gap_gt_90d
- DQ exclude MAXR (late): price_gap_gt_90d
- DQ exclude MAXS (late): extreme_jump_bars
- DQ exclude MAXW (late): penny_median_raw_close
- DQ exclude MAXY (late): penny_median_raw_close
- DQ exclude MAY (late): price_gap_gt_90d
- DQ exclude MBAY (late): sentinel_bars
- DQ exclude MBHIQ (late): sentinel_bars
- DQ exclude MCC (late): extreme_jump_bars
- DQ exclude MCEP (late): extreme_jump_bars
- DQ exclude MCM (late): extreme_jump_bars
- DQ exclude MCOAQ (late): sentinel_bars
- DQ exclude MDR (late): price_gap_gt_90d
- DQ exclude MDS (late): extreme_jump_bars
- DQ exclude MDVL (late): sentinel_bars
- DQ exclude MDVLQ (late): extreme_jump_bars
- DQ exclude MEDC (late): price_gap_gt_90d
- DQ exclude MEDS (late): sentinel_bars
- DQ exclude MEH (late): price_gap_gt_90d
- DQ exclude MEL (late): sentinel_bars
- DQ exclude MER (late): price_gap_gt_90d
- DQ exclude MGG (late): extreme_jump_bars
- DQ exclude MGI (late): extreme_jump_bars
- DQ exclude MGXX (late): sentinel_bars
- DQ exclude MHL (late): extreme_jump_bars
- DQ exclude MICS (late): penny_median_raw_close
- DQ exclude MICT (late): price_gap_gt_90d
- DQ exclude MIFI (late): extreme_jump_bars
- DQ exclude MIIX (late): sentinel_bars
- DQ exclude MIL (late): price_gap_gt_90d
- DQ exclude MILL (late): sentinel_bars
- DQ exclude MITA (late): price_gap_gt_90d
- DQ exclude MIX (late): penny_median_raw_close
- DQ exclude MKTSQ (late): sentinel_bars
- DQ exclude MLK (late): sentinel_bars
- DQ exclude MMAT (late): price_gap_gt_90d
- DQ exclude MNMD (late): sentinel_bars
- DQ exclude MOSC (late): price_gap_gt_90d
- DQ exclude MOSC-U (late): price_gap_gt_90d
- DQ exclude MOSC-WS (late): price_gap_gt_90d
- DQ exclude MR (late): extreme_jump_bars
- DQ exclude MRE (late): price_gap_gt_90d
- DQ exclude MRH (late): price_gap_gt_90d
- DQ exclude MRIC (late): price_gap_gt_90d
- DQ exclude MSCA (late): price_gap_gt_90d
- DQ exclude MSK (late): price_gap_gt_90d
- DQ exclude MSZ (late): extreme_jump_bars
- DQ exclude MTL (late): nonpositive_raw_close
- DQ exclude MTP (late): sentinel_bars
- DQ exclude MTSXY (late): sentinel_bars
- DQ exclude MVL (late): extreme_jump_bars
- DQ exclude MWI (late): price_gap_gt_90d
- DQ exclude MWJ (late): price_gap_gt_90d
- DQ exclude MWP (late): price_gap_gt_90d
- DQ exclude NAKD (late): price_gap_gt_90d
- DQ exclude NAL (late): extreme_jump_bars
- DQ exclude NBEV (late): sentinel_bars
- DQ exclude NBRV (late): extreme_jump_bars
- DQ exclude NCBS (late): price_gap_gt_90d
- DQ exclude NCF (late): price_gap_gt_90d
- DQ exclude NCH (late): price_gap_gt_90d
- DQ exclude NCMV (late): penny_median_raw_close
- DQ exclude NDN (late): price_gap_gt_90d
- DQ exclude NEB (late): price_gap_gt_90d
- DQ exclude NEPT (late): sentinel_bars
- DQ exclude NER (late): extreme_jump_bars
- DQ exclude NEW (late): extreme_jump_bars
- DQ exclude NFEC (late): price_gap_gt_90d
- DQ exclude NFP (late): extreme_jump_bars
- DQ exclude NFS (late): price_gap_gt_90d
- DQ exclude NGH (late): penny_median_raw_close
- DQ exclude NHL (late): extreme_jump_bars
- DQ exclude NHLD (late): extreme_jump_bars
- DQ exclude NHP (late): extreme_jump_bars
- DQ exclude NHY (late): extreme_jump_bars
- DQ exclude NLC (late): extreme_jump_bars
- DQ exclude NLCS (late): extreme_jump_bars
- DQ exclude NLTX (late): nonpositive_raw_close
- DQ exclude NM (late): extreme_jump_bars
- DQ exclude NMTI (late): sentinel_bars
- DQ exclude NMTR (late): extreme_jump_bars
- DQ exclude NNS (late): price_gap_gt_90d
- DQ exclude NOR (late): price_gap_gt_90d
- DQ exclude NOVN (late): price_gap_gt_90d
- DQ exclude NRCIB (late): price_gap_gt_90d
- DQ exclude NRDSQ (late): sentinel_bars
- DQ exclude NRGP (late): price_gap_gt_90d
- DQ exclude NRL (late): sentinel_bars
- DQ exclude NRTLQ (late): sentinel_bars
- DQ exclude NSE (late): penny_median_raw_close
- DQ exclude NSK (late): sentinel_bars
- DQ exclude NSR (late): extreme_jump_bars
- DQ exclude NST (late): extreme_jump_bars
- DQ exclude NSTLQ (late): sentinel_bars
- DQ exclude NTO (late): price_gap_gt_90d
- DQ exclude NUKK (late): sentinel_bars
- DQ exclude NUZE (late): extreme_jump_bars
- DQ exclude NVE (late): price_gap_gt_90d
- DQ exclude NVLS (late): price_gap_gt_90d
- DQ exclude NVTK (late): sentinel_bars
- DQ exclude NWGI (late): sentinel_bars
- DQ exclude NXGN (late): nonpositive_raw_close
- DQ exclude NYNY (late): extreme_jump_bars
- DQ exclude OBLN (late): extreme_jump_bars
- DQ exclude OCA (late): price_gap_gt_90d
- DQ exclude OCHTQ (late): sentinel_bars
- DQ exclude OHGI (late): sentinel_bars
- DQ exclude OHP (late): price_gap_gt_90d
- DQ exclude OIG (late): sentinel_bars
- DQ exclude OMM (late): price_gap_gt_90d
- DQ exclude OMNI (late): price_gap_gt_90d
- DQ exclude ONCR (late): sentinel_bars
- DQ exclude ONCS (late): sentinel_bars
- DQ exclude ONE (late): price_gap_gt_90d
- DQ exclude ONEM (late): nonpositive_raw_close
- DQ exclude ONSM (late): extreme_jump_bars
- DQ exclude OPHT (late): price_gap_gt_90d
- DQ exclude ORCH (late): price_gap_gt_90d
- DQ exclude ORCT (late): sentinel_bars
- DQ exclude ORIG (late): sentinel_bars
- DQ exclude ORK (late): price_gap_gt_90d
- DQ exclude OSAT (late): sentinel_bars
- DQ exclude OSB (late): extreme_jump_bars
- DQ exclude OTIV (late): price_gap_gt_90d
- DQ exclude OTRK (late): price_gap_gt_90d
- DQ exclude OTT (late): price_gap_gt_90d
- DQ exclude OV (late): sentinel_bars
- DQ exclude OXF (late): price_gap_gt_90d
- DQ exclude OYST (late): nonpositive_raw_close
- DQ exclude PACD (late): price_gap_gt_90d
- DQ exclude PACW (late): nonpositive_raw_close
- DQ exclude PALDF (late): extreme_jump_bars
- DQ exclude PAS (late): price_gap_gt_90d
- DQ exclude PBG (late): extreme_jump_bars
- DQ exclude PCOM (late): price_gap_gt_90d
- DQ exclude PCSB (late): nonpositive_raw_close
- DQ exclude PCZ (late): price_gap_gt_90d
- DQ exclude PDG (late): price_gap_gt_90d
- DQ exclude PEGY (late): sentinel_bars
- DQ exclude PEIX (late): extreme_jump_bars
- DQ exclude PFCO (late): sentinel_bars
- DQ exclude PFHD (late): nonpositive_raw_close
- DQ exclude PFIE (late): price_gap_gt_90d
- DQ exclude PFSW (late): nonpositive_raw_close
- DQ exclude PGE (late): extreme_jump_bars
- DQ exclude PGICQ (late): sentinel_bars
- DQ exclude PGL (late): price_gap_gt_90d
- DQ exclude PGS (late): extreme_jump_bars
- DQ exclude PHC (late): price_gap_gt_90d
- DQ exclude PKD (late): extreme_jump_bars
- DQ exclude PLXP (late): sentinel_bars
- DQ exclude PME (late): sentinel_bars
- DQ exclude PNB (late): extreme_jump_bars
- DQ exclude PNP (late): price_gap_gt_90d
- DQ exclude POG (late): sentinel_bars
- DQ exclude POP (late): price_gap_gt_90d
- DQ exclude POS (late): sentinel_bars
- DQ exclude POSH (late): nonpositive_raw_close
- DQ exclude PPP (late): extreme_jump_bars
- DQ exclude PRAN (late): price_gap_gt_90d
- DQ exclude PRBG (late): sentinel_bars
- DQ exclude PRGN (late): extreme_jump_bars
- DQ exclude PRMX (late): sentinel_bars
- DQ exclude PROG (late): price_gap_gt_90d
- DQ exclude PROX (late): sentinel_bars
- DQ exclude PRTG (late): sentinel_bars
- DQ exclude PRTK (late): extreme_jump_bars
- DQ exclude PSFE-WT (late): penny_median_raw_close
- DQ exclude PSTI (late): extreme_jump_bars
- DQ exclude PTE (late): sentinel_bars
- DQ exclude PTI (late): extreme_jump_bars
- DQ exclude PTIE (late): price_gap_gt_90d
- DQ exclude PTT (late): extreme_jump_bars
- DQ exclude PUB (late): extreme_jump_bars
- DQ exclude PVT-U (late): price_gap_gt_90d
- DQ exclude PVX (late): extreme_jump_bars
- DQ exclude PWAVQ (late): sentinel_bars
- DQ exclude PWI (late): extreme_jump_bars
- DQ exclude PXT (late): extreme_jump_bars
- DQ exclude QIPT (late): penny_median_raw_close
- DQ exclude QLGN (late): sentinel_bars
- DQ exclude QOBJ (late): sentinel_bars
- DQ exclude QPAC (late): extreme_jump_bars
- DQ exclude QUMU (late): nonpositive_raw_close
- DQ exclude RADI (late): price_gap_gt_90d
- DQ exclude RBD (late): sentinel_bars
- DQ exclude RBN (late): price_gap_gt_90d
- DQ exclude RCRT (late): sentinel_bars
- DQ exclude REPB (late): price_gap_gt_90d
- DQ exclude REV (late): extreme_jump_bars
- DQ exclude REXN (late): extreme_jump_bars
- DQ exclude REXX (late): extreme_jump_bars
- DQ exclude REY (late): extreme_jump_bars
- DQ exclude RFS (late): price_gap_gt_90d
- DQ exclude RGO (late): sentinel_bars
- DQ exclude RGSE (late): sentinel_bars
- DQ exclude RICO (late): sentinel_bars
- DQ exclude RMBL (late): price_gap_gt_90d
- DQ exclude RMGC (late): price_gap_gt_90d
- DQ exclude RML (late): extreme_jump_bars
- DQ exclude RON (late): sentinel_bars
- DQ exclude ROSD (late): sentinel_bars
- DQ exclude ROSG (late): extreme_jump_bars
- DQ exclude RRD (late): extreme_jump_bars
- DQ exclude RSH (late): extreme_jump_bars
- DQ exclude RST (late): price_gap_gt_90d
- DQ exclude RSTN (late): sentinel_bars
- DQ exclude RTRX (late): sentinel_bars
- DQ exclude RTW (late): price_gap_gt_90d
- DQ exclude RVLP (late): sentinel_bars
- DQ exclude RWE (late): price_gap_gt_90d
- DQ exclude RX (late): price_gap_gt_90d
- DQ exclude RXDX (late): price_gap_gt_90d
- DQ exclude RYC (late): price_gap_gt_90d
- DQ exclude RZA (late): nonpositive_raw_close
- DQ exclude SAE (late): sentinel_bars
- DQ exclude SAMA (late): nonpositive_raw_close
- DQ exclude SAMAU (late): price_gap_gt_90d
- DQ exclude SASI (late): extreme_jump_bars
- DQ exclude SATCQ (late): sentinel_bars
- DQ exclude SBER (late): sentinel_bars
- DQ exclude SBKC (late): sentinel_bars
- DQ exclude SBMC (late): price_gap_gt_90d
- DQ exclude SBSA (late): extreme_jump_bars
- DQ exclude SCLD (late): sentinel_bars
- DQ exclude SCMR (late): penny_median_raw_close
- DQ exclude SCOA (late): nonpositive_raw_close
- DQ exclude SCOXQ (late): price_gap_gt_90d
- DQ exclude SCPL (late): nonpositive_raw_close
- DQ exclude SCR (late): penny_median_raw_close
- DQ exclude SCU (late): extreme_jump_bars
- DQ exclude SDC (late): nonpositive_raw_close
- DQ exclude SDNA (late): sentinel_bars
- DQ exclude SDW (late): sentinel_bars
- DQ exclude SEDA-UN (late): penny_median_raw_close
- DQ exclude SESN (late): nonpositive_raw_close
- DQ exclude SFE (late): sentinel_bars
- DQ exclude SFP (late): price_gap_gt_90d
- DQ exclude SFXE (late): sentinel_bars
- DQ exclude SGLB (late): sentinel_bars
- DQ exclude SGO (late): extreme_jump_bars
- DQ exclude SGOC (late): price_gap_gt_90d
- DQ exclude SGT (late): extreme_jump_bars
- DQ exclude SHS (late): extreme_jump_bars
- DQ exclude SHU (late): penny_median_raw_close
- DQ exclude SIB (late): extreme_jump_bars
- DQ exclude SIE (late): extreme_jump_bars
- DQ exclude SIR (late): extreme_jump_bars
- DQ exclude SKBI (late): price_gap_gt_90d
- DQ exclude SKFB (late): extreme_jump_bars
- DQ exclude SKH (late): price_gap_gt_90d
- DQ exclude SKS (late): extreme_jump_bars
- DQ exclude SLAM (late): price_gap_gt_90d
- DQ exclude SLNK (late): price_gap_gt_90d
- DQ exclude SLR (late): extreme_jump_bars
- DQ exclude SMLP (late): sentinel_bars
- DQ exclude SMRA (late): price_gap_gt_90d
- DQ exclude SMS (late): price_gap_gt_90d
- DQ exclude SNG (late): extreme_jump_bars
- DQ exclude SNKTY (late): sentinel_bars
- DQ exclude SNRA (late): price_gap_gt_90d
- DQ exclude SNSS (late): penny_median_raw_close
- DQ exclude SOA (late): price_gap_gt_90d
- DQ exclude SONN (late): sentinel_bars
- DQ exclude SOV (late): extreme_jump_bars
- DQ exclude SPEL (late): price_gap_gt_90d
- DQ exclude SPEX (late): sentinel_bars
- DQ exclude SPM (late): extreme_jump_bars
- DQ exclude SPNE (late): nonpositive_raw_close
- DQ exclude SQBG (late): sentinel_bars
- DQ exclude SRA (late): extreme_jump_bars
- DQ exclude SRCTQ (late): sentinel_bars
- DQ exclude SRR (late): sentinel_bars
- DQ exclude SRX (late): extreme_jump_bars
- DQ exclude SSE (late): price_gap_gt_90d
- DQ exclude SSNT (late): extreme_jump_bars
- DQ exclude STI-WS-B (late): extreme_jump_bars
- DQ exclude STOR (late): nonpositive_raw_close
- DQ exclude STR (late): sentinel_bars
- DQ exclude STRZB (late): price_gap_gt_90d
- DQ exclude STW (late): price_gap_gt_90d
- DQ exclude SUG (late): extreme_jump_bars
- DQ exclude SUNW (late): sentinel_bars
- DQ exclude SUR (late): extreme_jump_bars
- DQ exclude SUS (late): price_gap_gt_90d
- DQ exclude SVFD (late): extreme_jump_bars
- DQ exclude SVNTQ (late): sentinel_bars
- DQ exclude SWD (late): sentinel_bars
- DQ exclude SWW (late): sentinel_bars
- DQ exclude SYN (late): sentinel_bars
- DQ exclude SYNC (late): price_gap_gt_90d
- DQ exclude SYTA (late): penny_median_raw_close
- DQ exclude TAMR (late): sentinel_bars
- DQ exclude TANN (late): price_gap_gt_90d
- DQ exclude TBE (late): extreme_jump_bars
- DQ exclude TBP (late): penny_median_raw_close
- DQ exclude TBUSQ (late): sentinel_bars
- DQ exclude TCA (late): price_gap_gt_90d
- DQ exclude TCAP (late): sentinel_bars
- DQ exclude TCR (late): price_gap_gt_90d
- DQ exclude TCT (late): price_gap_gt_90d
- DQ exclude TEE (late): price_gap_gt_90d
- DQ exclude TEUM (late): sentinel_bars
- DQ exclude TGISQ (late): sentinel_bars
- DQ exclude TGO (late): extreme_jump_bars
- DQ exclude TIE (late): extreme_jump_bars
- DQ exclude TIN (late): extreme_jump_bars
- DQ exclude TIT (late): sentinel_bars
- DQ exclude TKMR (late): price_gap_gt_90d
- DQ exclude TMD (late): extreme_jump_bars
- DQ exclude TMPO (late): sentinel_bars
- DQ exclude TND (late): sentinel_bars
- DQ exclude TNM (late): extreme_jump_bars
- DQ exclude TNO (late): sentinel_bars
- DQ exclude TNT (late): extreme_jump_bars
- DQ exclude TOM (late): sentinel_bars
- DQ exclude TORC (late): price_gap_gt_90d
- DQ exclude TOY (late): price_gap_gt_90d
- DQ exclude TPTX (late): price_gap_gt_90d
- DQ exclude TRA (late): sentinel_bars
- DQ exclude TRCH (late): price_gap_gt_90d
- DQ exclude TREC (late): sentinel_bars
- DQ exclude TRHC (late): nonpositive_raw_close
- DQ exclude TRIS (late): sentinel_bars
- DQ exclude TRQ (late): extreme_jump_bars
- DQ exclude TRZ (late): sentinel_bars
- DQ exclude TSD (late): extreme_jump_bars
- DQ exclude TSR (late): price_gap_gt_90d
- DQ exclude TST (late): extreme_jump_bars
- DQ exclude TTO (late): penny_median_raw_close
- DQ exclude TTS (late): price_gap_gt_90d
- DQ exclude TTX (late): sentinel_bars
- DQ exclude TVX (late): penny_median_raw_close
- DQ exclude TWD (late): price_gap_gt_90d
- DQ exclude TXM (late): extreme_jump_bars
- DQ exclude TYME (late): price_gap_gt_90d
- DQ exclude UBI (late): sentinel_bars
- DQ exclude UBID (late): sentinel_bars
- DQ exclude UCBH (late): sentinel_bars
- DQ exclude UCM (late): penny_median_raw_close
- DQ exclude UDS (late): price_gap_gt_90d
- DQ exclude UEPS (late): price_gap_gt_90d
- DQ exclude UIC (late): extreme_jump_bars
- DQ exclude UNAMQ (late): sentinel_bars
- DQ exclude UPL (late): extreme_jump_bars
- DQ exclude UPR (late): sentinel_bars
- DQ exclude USS (late): extreme_jump_bars
- DQ exclude UVN (late): penny_median_raw_close
- DQ exclude VAPE (late): penny_median_raw_close
- DQ exclude VAPHQ (late): penny_median_raw_close
- DQ exclude VBIV (late): extreme_jump_bars
- DQ exclude VBLT (late): nonpositive_raw_close
- DQ exclude VELTF (late): sentinel_bars
- DQ exclude VIEW (late): sentinel_bars
- DQ exclude VIIAU (late): nonpositive_raw_close
- DQ exclude VLDR (late): nonpositive_raw_close
- DQ exclude VLDRW (late): nonpositive_raw_close
- DQ exclude VLG (late): price_gap_gt_90d
- DQ exclude VLY-WS (late): sentinel_bars
- DQ exclude VNA (late): extreme_jump_bars
- DQ exclude VNBCQ (late): sentinel_bars
- DQ exclude VNX (late): sentinel_bars
- DQ exclude VPCO (late): sentinel_bars
- DQ exclude VPI (late): price_gap_gt_90d
- DQ exclude VRCC (late): sentinel_bars
- DQ exclude VRI (late): penny_median_raw_close
- DQ exclude VTIQ (late): nonpositive_raw_close
- DQ exclude VTL (late): extreme_jump_bars
- DQ exclude VTNR (late): sentinel_bars
- DQ exclude VTNRQ (late): sentinel_bars
- DQ exclude VVC (late): extreme_jump_bars
- DQ exclude VWE (late): price_gap_gt_90d
- DQ exclude WAVD (late): penny_median_raw_close
- DQ exclude WAVX (late): extreme_jump_bars
- DQ exclude WBB (late): price_gap_gt_90d
- DQ exclude WCRX (late): price_gap_gt_90d
- DQ exclude WEBM (late): price_gap_gt_90d
- DQ exclude WGAT (late): sentinel_bars
- DQ exclude WHCI (late): extreme_jump_bars
- DQ exclude WIC (late): price_gap_gt_90d
- DQ exclude WIN (late): extreme_jump_bars
- DQ exclude WLL (late): extreme_jump_bars
- DQ exclude WLM (late): price_gap_gt_90d
- DQ exclude WLVTQ (late): sentinel_bars
- DQ exclude WMC (late): nonpositive_raw_close
- DQ exclude WMD (late): price_gap_gt_90d
- DQ exclude WRES (late): sentinel_bars
- DQ exclude WSB (late): price_gap_gt_90d
- DQ exclude WSGI (late): penny_median_raw_close
- DQ exclude WTCT (late): sentinel_bars
- DQ exclude WTR (late): nonpositive_raw_close
- DQ exclude WTRH (late): extreme_jump_bars
- DQ exclude WTSL (late): sentinel_bars
- DQ exclude WWY (late): extreme_jump_bars
- DQ exclude WZR (late): price_gap_gt_90d
- DQ exclude XBKS (late): extreme_jump_bars
- DQ exclude XGTI (late): price_gap_gt_90d
- DQ exclude XRF (late): extreme_jump_bars
- DQ exclude XTEL (late): sentinel_bars
- DQ exclude YCC (late): extreme_jump_bars
- DQ exclude YELL (late): sentinel_bars
- DQ exclude YES (late): penny_median_raw_close
- DQ exclude YRCW (late): sentinel_bars
- DQ exclude YRK (late): extreme_jump_bars
- DQ exclude YVR (late): sentinel_bars
- DQ exclude YZC (late): price_gap_gt_90d
- DQ exclude ZAZZT (late): sentinel_bars
- DQ exclude ZBZZT (late): sentinel_bars
- DQ exclude ZEV (late): extreme_jump_bars
- DQ exclude ZPLS (late): sentinel_bars
- DQ exclude ZYNE (late): nonpositive_raw_close
- FIX-1 exclude IMNN (living): ratio_spikes(1)
- FIX-1 replace -> FEED

## Full panel (211 rows)

| # | symbol | sleeve | sector | cell/era | vol | cap ($M) | window |
|---|---|---|---|---|---|---|---|
| 1 | AIPC | early | — | post_2010 | 0.51 | — | 1997-12-31→2010-07-27 |
| 2 | AK | early | — | dotcom_2000_2003 | 0.53 | — | 1999-01-04→2002-06-14 |
| 3 | AMPH1 | early | — | post_2010 | 0.52 | — | 1997-12-31→2010-11-30 |
| 4 | AMSI | early | — | gfc_cycle_2004_2009 | 1.77 | — | 2000-04-07→2006-06-30 |
| 5 | ANDW | early | — | gfc_cycle_2004_2009 | 0.57 | — | 1997-12-31→2007-12-27 |
| 6 | BJS | early | — | post_2010 | 0.49 | — | 1997-12-31→2010-04-28 |
| 7 | CBNY1 | early | — | dotcom_2000_2003 | 0.53 | — | 1997-12-31→2001-11-09 |
| 8 | CDTS | early | — | dotcom_2000_2003 | 1.37 | — | 1999-01-04→2002-12-17 |
| 9 | CLK | early | — | gfc_cycle_2004_2009 | 0.54 | — | 1998-08-19→2007-03-12 |
| 10 | CLPA | early | — | dotcom_2000_2003 | 1.25 | — | 1998-11-05→2003-06-11 |
| 11 | DEBS | early | — | gfc_cycle_2004_2009 | 0.42 | — | 1999-01-04→2007-10-23 |
| 12 | DGLV | early | — | dotcom_2000_2003 | 2.16 | — | 1999-02-17→2001-12-03 |
| 13 | DYSVY | early | — | gfc_cycle_2004_2009 | 0.44 | — | 1997-12-31→2009-07-27 |
| 14 | ECTX1 | early | — | post_2010 | 0.74 | — | 1999-10-26→2010-01-13 |
| 15 | ENPT1 | early | — | gfc_cycle_2004_2009 | 1.24 | — | 1999-01-04→2009-08-07 |
| 16 | HCDC | early | — | dotcom_2000_2003 | 1.08 | — | 1999-01-04→2001-08-13 |
| 17 | ITIG | early | — | post_2010 | 0.94 | — | 1999-01-04→2010-07-26 |
| 18 | KTII | early | — | post_2010 | 0.44 | — | 1997-12-31→2010-04-01 |
| 19 | LIHR | early | — | post_2010 | 0.59 | — | 1997-12-31→2010-08-27 |
| 20 | MEA1 | early | — | dotcom_2000_2003 | 0.41 | — | 1997-12-31→2002-01-29 |
| 21 | NAMC | early | — | post_2010 | 2.07 | — | 1999-01-04→2010-03-01 |
| 22 | NETM | early | — | gfc_cycle_2004_2009 | 0.91 | — | 1999-01-04→2008-06-18 |
| 23 | PNWB | early | — | dotcom_2000_2003 | 0.34 | — | 1999-01-04→2003-10-31 |
| 24 | PSIXQ | early | — | dotcom_2000_2003 | 2.11 | — | 1999-01-04→2001-04-02 |
| 25 | RHT1 | early | — | gfc_cycle_2004_2009 | 0.69 | — | 1999-01-04→2004-01-23 |
| 26 | RSE1 | early | — | gfc_cycle_2004_2009 | 0.22 | — | 1997-12-31→2004-11-12 |
| 27 | STEL1 | early | — | gfc_cycle_2004_2009 | 0.79 | — | 1999-01-04→2006-12-14 |
| 28 | SXNB | early | — | dotcom_2000_2003 | 0.37 | — | 1997-12-31→2001-11-16 |
| 29 | SY2 | early | — | post_2010 | 0.43 | — | 1997-12-31→2010-07-28 |
| 30 | UST1 | early | — | gfc_cycle_2004_2009 | 0.28 | — | 1997-12-31→2009-01-05 |
| 31 | VION | early | — | post_2010 | 1.53 | — | 1997-12-31→2010-04-09 |
| 32 | VOXW | early | — | post_2010 | 1.88 | — | 1997-12-31→2010-12-29 |
| 33 | ZNT | early | — | post_2010 | 0.33 | — | 1997-12-31→2010-05-20 |
| 34 | ARDNA | late | — | y2011_2015 | 0.39 | — | 1990-01-02→2014-02-19 |
| 35 | ASBB | late | — | y2016_2019 | 0.23 | — | 2011-10-12→2017-09-29 |
| 36 | ATMI | late | — | y2011_2015 | 0.52 | — | 1999-01-04→2014-04-29 |
| 37 | BGNE | late | Healthcare | y2020_plus | 0.58 | — | 2016-02-03→2024-12-31 |
| 38 | BTCM | late | Technology | y2020_plus | 0.95 | 476 | 2013-11-22→2025-12-19 |
| 39 | CRTP | late | — | y2011_2015 | 1.46 | — | 2000-01-31→2013-10-02 |
| 40 | DLPH | late | Consumer Cyclical | y2020_plus | 0.49 | 1,867 | 2011-11-17→2020-10-02 |
| 41 | EQGP | late | — | y2016_2019 | 0.39 | — | 2015-05-12→2019-01-10 |
| 42 | FBMI | late | — | y2011_2015 | 0.43 | — | 1999-01-04→2014-05-30 |
| 43 | FMER | late | — | y2016_2019 | 0.35 | — | 1997-12-31→2016-08-15 |
| 44 | GMKYY | late | — | y2016_2019 | 0.44 | — | 1999-01-04→2016-03-07 |
| 45 | GST | late | — | y2016_2019 | 0.96 | — | 2006-01-05→2018-09-06 |
| 46 | HCBK | late | — | y2011_2015 | 0.29 | — | 1999-07-13→2015-10-30 |
| 47 | HEARQ | late | — | y2011_2015 | 0.85 | — | 1999-01-04→2012-06-15 |
| 48 | IDSA | late | — | y2016_2019 | 1.43 | 22 | 1997-12-31→2019-12-30 |
| 49 | LPT | late | — | y2020_plus | 0.32 | 3,984 | 1997-12-31→2020-02-03 |
| 50 | MCOX | late | — | y2016_2019 | 1.15 | — | 2010-10-26→2016-04-14 |
| 51 | MLND | late | Healthcare | y2020_plus | 0.96 | — | 2012-11-12→2022-02-18 |
| 52 | NYRT | late | — | y2016_2019 | 0.40 | 115 | 2014-04-15→2018-11-02 |
| 53 | ORTX | late | Healthcare | y2020_plus | 0.79 | 442 | 2018-10-31→2024-02-05 |
| 54 | QTWW | late | — | y2016_2019 | 1.38 | — | 2002-07-16→2016-03-31 |
| 55 | RBI | late | — | y2020_plus | 0.48 | — | 2005-04-25→2020-07-31 |
| 56 | ROSE1 | late | — | y2011_2015 | 0.53 | — | 2006-02-13→2015-07-20 |
| 57 | RT | late | — | y2016_2019 | 0.54 | — | 1997-12-31→2017-12-21 |
| 58 | RYCE | late | — | y2020_plus | 1.03 | — | 2012-10-10→2021-01-28 |
| 59 | SQ | late | — | y2020_plus | 0.59 | — | 2015-11-19→2025-01-21 |
| 60 | SQNM | late | — | y2016_2019 | 0.98 | — | 2000-02-01→2016-09-06 |
| 61 | SSFC | late | — | y2011_2015 | 0.66 | — | 1996-10-03→2014-04-07 |
| 62 | TGAN | late | — | y2020_plus | 1.25 | — | 2020-07-29→2024-07-01 |
| 63 | UBP | late | — | y2020_plus | 0.34 | — | 1990-01-02→2023-08-17 |
| 64 | UZA | late | — | y2020_plus | 0.17 | — | 2011-05-16→2021-08-31 |
| 65 | VTSS | late | — | y2011_2015 | 0.84 | — | 1997-12-31→2015-04-27 |
| 66 | XSELY | late | — | y2011_2015 | 3.02 | — | 2007-03-09→2013-05-16 |
| 67 | ACAD | living | Healthcare | large_liquid/high | 0.82 | 1,979 | 2004-05-27→2026-06-10 |
| 68 | ADNT | living | Consumer Cyclical | large_liquid/high | 0.64 | 3,562 | 2016-10-17→2026-06-10 |
| 69 | AEYE | living | Technology | small/high | 1.28 | 41 | 2013-04-26→2026-06-10 |
| 70 | AGEN | living | Healthcare | small/high | 0.80 | 315 | 2000-02-04→2026-06-10 |
| 71 | AGNC | living | Real Estate | large_liquid/low | 0.27 | 1,938 | 2008-05-15→2026-06-10 |
| 72 | AKAM | living | Technology | large_liquid/high | 0.62 | 8,187 | 1999-10-29→2026-06-10 |
| 73 | AKBA | living | Healthcare | mid/high | 0.96 | 403 | 2014-03-20→2026-06-10 |
| 74 | ALGN | living | Healthcare | large_liquid/high | 0.60 | 2,349 | 2001-01-26→2026-06-10 |
| 75 | ANGI | living | Communication Services | large_liquid/high | 0.63 | 3,971 | 2011-11-17→2026-06-10 |
| 76 | APLS | living | Healthcare | large_liquid/high | 0.75 | 2,896 | 2017-11-09→2026-06-10 |
| 77 | ARKR | living | Consumer Cyclical | small/low | 0.47 | 46 | 1990-01-03→2026-06-10 |
| 78 | ARMK | living | Industrials | large_liquid/low | 0.36 | 5,999 | 2013-12-12→2026-06-10 |
| 79 | AUDC | living | Technology | small/high | 0.61 | 204 | 1999-05-28→2026-06-10 |
| 80 | AVTX | living | Healthcare | small/high | 1.38 | 203 | 2015-10-14→2026-06-10 |
| 81 | AX | living | Financials | mid/low | 0.44 | 1,126 | 2005-03-15→2026-06-10 |
| 82 | AZO | living | Consumer Cyclical | large_liquid/low | 0.28 | 13,768 | 1991-04-02→2026-06-10 |
| 83 | BB | living | Technology | large_liquid/high | 0.67 | 5,525 | 1999-02-04→2026-06-10 |
| 84 | BCS | living | Financials | large_liquid/low | 0.49 | 36,936 | 1990-01-02→2026-06-10 |
| 85 | BELFA | living | Technology | small/low | 0.55 | 211 | 1990-01-02→2026-06-10 |
| 86 | BGMS | living | Healthcare | large_liquid/high | 0.67 | 19,589 | 2004-03-16→2026-06-10 |
| 87 | BKH | living | Utilities | mid/low | 0.28 | 835 | 1990-01-02→2026-06-10 |
| 88 | BLDR | living | Industrials | mid/high | 0.68 | 789 | 2005-06-22→2026-06-10 |
| 89 | BMRC | living | Financials | small/low | 0.30 | 135 | 1994-04-28→2026-06-10 |
| 90 | BPOP | living | Financials | large_liquid/low | 0.45 | 2,670 | 1990-01-02→2026-06-10 |
| 91 | BRID | living | Consumer Defensive | small/low | 0.55 | 95 | 1990-01-02→2026-06-10 |
| 92 | BTU | living | Energy | large_liquid/high | 0.83 | 2,657 | 2017-04-03→2026-06-10 |
| 93 | CABO | living | Communication Services | large_liquid/low | 0.31 | 4,278 | 2015-06-11→2026-06-10 |
| 94 | CARS | living | Communication Services | mid/high | 0.60 | 1,080 | 2017-05-18→2026-06-10 |
| 95 | CBRL | living | Consumer Cyclical | mid/low | 0.37 | 1,025 | 1990-01-02→2026-06-10 |
| 96 | CCU | living | Consumer Defensive | large_liquid/low | 0.28 | 1,958 | 1992-09-24→2026-06-10 |
| 97 | CHMI | living | Real Estate | small/low | 0.41 | 66 | 2013-10-04→2026-06-10 |
| 98 | CNC | living | Healthcare | large_liquid/low | 0.42 | 2,420 | 2001-12-13→2026-06-10 |
| 99 | COKE | living | Consumer Defensive | mid/low | 0.33 | 530 | 1990-01-02→2026-06-10 |
| 100 | CPB | living | Consumer Defensive | large_liquid/low | 0.23 | 8,058 | 1990-01-02→2026-06-10 |
| 101 | CRWS | living | Consumer Cyclical | small/high | 0.87 | 21 | 1990-01-02→2026-06-10 |
| 102 | CSGP | living | Real Estate | mid/low | 0.41 | 1,556 | 1998-07-01→2026-06-10 |
| 103 | CSPI | living | Technology | small/low | 0.54 | 9 | 1990-01-02→2026-06-10 |
| 104 | CTGO | living | Basic Materials | small/high | 1.34 | 89 | 2010-12-20→2026-06-10 |
| 105 | CUBE | living | Real Estate | mid/low | 0.38 | 1,631 | 2004-10-22→2026-06-10 |
| 106 | CYPH | living | Financials | small/high | 0.94 | 72 | 2017-01-25→2026-06-10 |
| 107 | CZNC | living | Financials | small/low | 0.37 | 109 | 1994-04-05→2026-06-10 |
| 108 | CZR | living | Consumer Cyclical | mid/high | 0.62 | 418 | 1992-12-07→2026-06-10 |
| 109 | DAN | living | Consumer Cyclical | large_liquid/high | 0.72 | 2,141 | 2008-01-02→2026-06-10 |
| 110 | DD | living | Basic Materials | large_liquid/low | 0.35 | 5,168 | 1990-01-02→2026-06-10 |
| 111 | DDD | living | Technology | mid/high | 0.71 | 794 | 1990-01-02→2026-06-10 |
| 112 | DDS | living | Consumer Cyclical | mid/low | 0.55 | 1,406 | 1990-01-02→2026-06-10 |
| 113 | DIOD | living | Technology | mid/low | 0.51 | 1,105 | 1990-01-02→2026-06-10 |
| 114 | DKL | living | Energy | small/low | 0.44 | 339 | 2012-11-02→2026-06-10 |
| 115 | EDU | living | Consumer Defensive | large_liquid/high | 0.59 | 3,882 | 2006-09-07→2026-06-10 |
| 116 | EFR | living | Financials | small/low | 0.17 | 269 | 2003-11-25→2026-06-10 |
| 117 | EGBN | living | Financials | small/low | 0.41 | 235 | 1999-07-14→2026-06-10 |
| 118 | EGO | living | Basic Materials | large_liquid/high | 0.94 | 1,918 | 2001-06-27→2026-06-10 |
| 119 | EGY | living | Energy | small/high | 0.84 | 181 | 1993-01-29→2026-06-10 |
| 120 | ENLV | living | Healthcare | small/high | 0.93 | 66 | 2014-07-31→2026-06-10 |
| 121 | ENPH | living | Technology | mid/high | 0.81 | 544 | 2012-03-30→2026-06-10 |
| 122 | ENS | living | Industrials | large_liquid/low | 0.42 | 2,294 | 2004-07-30→2026-06-10 |
| 123 | EPAC | living | Industrials | mid/low | 0.49 | 1,421 | 1990-01-02→2026-06-10 |
| 124 | EQBK | living | Financials | mid/low | 0.36 | 399 | 2015-11-11→2026-06-10 |
| 125 | ERO | living | Basic Materials | mid/low | 0.56 | 1,254 | 2017-10-20→2026-06-10 |
| 126 | ES | living | Utilities | large_liquid/low | 0.23 | 3,749 | 1990-01-02→2026-06-10 |
| 127 | ESP | living | Industrials | small/low | 0.31 | 29 | 1990-01-02→2026-06-10 |
| 128 | EVI | living | Industrials | small/high | 0.76 | 8 | 1990-01-02→2026-06-10 |
| 129 | EVTC | living | Technology | mid/low | 0.30 | 1,738 | 2013-04-12→2026-06-10 |
| 130 | EXPE | living | Consumer Cyclical | large_liquid/high | 1.08 | 10,023 | 2005-07-20→2026-06-10 |
| 131 | EYE | living | Consumer Cyclical | large_liquid/low | 0.55 | 2,699 | 2017-10-26→2026-06-10 |
| 132 | FAST | living | Industrials | large_liquid/low | 0.33 | 8,169 | 1990-01-02→2026-06-10 |
| 133 | FCEL | living | Industrials | large_liquid/high | 0.92 | 10,538 | 1992-06-25→2026-06-10 |
| 134 | FCN | living | Industrials | mid/low | 0.40 | 1,628 | 1996-05-09→2026-06-10 |
| 135 | FEED | living | Healthcare | small/high | 1.00 | 21 | 2015-05-28→2026-06-10 |
| 136 | FFBC | living | Financials | mid/low | 0.38 | 524 | 1990-01-02→2026-06-10 |
| 137 | FNF | living | Financials | large_liquid/low | 0.35 | 4,880 | 2005-10-14→2026-06-10 |
| 138 | FNKO | living | Consumer Cyclical | mid/high | 0.80 | 505 | 2017-11-02→2026-06-10 |
| 139 | FOSL | living | Consumer Cyclical | mid/high | 0.66 | 1,324 | 1993-04-12→2026-06-10 |
| 140 | FSM | living | Basic Materials | mid/high | 0.70 | 547 | 2005-07-27→2026-06-10 |
| 141 | FTEK | living | Industrials | small/high | 0.73 | 89 | 1993-09-08→2026-06-10 |
| 142 | FXNC | living | Financials | small/low | 0.36 | 36 | 1996-06-27→2026-06-10 |
| 143 | GAIA | living | Communication Services | small/low | 0.56 | 159 | 1999-10-29→2026-06-10 |
| 144 | GCTK | living | Healthcare | large_liquid/high | 1.76 | 53,836 | 2013-04-25→2026-06-10 |
| 145 | GENE | living | Healthcare | mid/high | 1.16 | 559 | 2005-09-06→2026-06-10 |
| 146 | GROW | living | Financials | small/high | 0.72 | 36 | 1990-01-02→2026-06-10 |
| 147 | GRPN | living | Communication Services | large_liquid/high | 0.78 | 2,157 | 2011-11-04→2026-06-10 |
| 148 | GSBC | living | Financials | small/low | 0.35 | 237 | 1990-01-03→2026-06-10 |
| 149 | GSM | living | Basic Materials | mid/high | 0.67 | 948 | 2009-07-30→2026-06-10 |
| 150 | GWRE | living | Technology | large_liquid/low | 0.35 | 5,574 | 2012-01-25→2026-06-10 |
| 151 | HAL | living | Energy | large_liquid/low | 0.47 | 23,428 | 1990-01-02→2026-06-10 |
| 152 | HAS | living | Consumer Cyclical | large_liquid/low | 0.33 | 3,561 | 1990-01-02→2026-06-10 |
| 153 | HCI | living | Financials | small/low | 0.45 | 311 | 2008-07-31→2026-06-10 |
| 154 | HCM | living | Healthcare | large_liquid/high | 0.61 | 3,160 | 2016-03-17→2026-06-10 |
| 155 | HHS | living | Industrials | mid/low | 0.51 | 436 | 1993-11-04→2026-06-10 |
| 156 | HLIO | living | Industrials | mid/low | 0.48 | 566 | 1997-01-09→2026-06-10 |
| 157 | HROW | living | Healthcare | small/high | 1.50 | 59 | 2007-09-28→2026-06-10 |
| 158 | HTT | living | Financials | mid/high | 0.86 | 504 | 2017-10-18→2026-06-10 |
| 159 | HUBG | living | Industrials | mid/low | 0.45 | 1,240 | 1996-03-13→2026-06-10 |
| 160 | ICHR | living | Technology | mid/high | 0.61 | 712 | 2016-12-09→2026-06-10 |
| 161 | IEP | living | Energy | mid/low | 0.41 | 905 | 1990-01-02→2026-06-11 |
| 162 | IFRX | living | Healthcare | small/high | 1.37 | 129 | 2017-11-08→2026-06-10 |
| 163 | INSM | living | Healthcare | small/high | 1.18 | 179 | 1991-02-15→2026-06-10 |
| 164 | ITIC | living | Financials | small/low | 0.38 | 71 | 1990-01-02→2026-06-10 |
| 165 | JBL | living | Technology | large_liquid/low | 0.50 | 4,051 | 1993-05-03→2026-06-11 |
| 166 | JCTC | living | Basic Materials | small/low | 0.48 | 28 | 1996-04-12→2026-06-11 |
| 167 | JOB | living | Industrials | small/high | 0.95 | 9 | 1990-01-02→2026-06-11 |
| 168 | KFFB | living | Financials | small/low | 0.39 | 43 | 1995-07-10→2026-06-10 |
| 169 | KOS | living | Energy | large_liquid/high | 0.68 | 2,853 | 2011-05-11→2026-06-11 |
| 170 | KRG | living | Real Estate | mid/high | 1.63 | 413 | 2004-08-11→2026-06-11 |
| 171 | LBRT | living | Energy | mid/high | 0.68 | 1,731 | 2018-01-11→2026-06-11 |
| 172 | LC | living | Financials | mid/high | 0.65 | 1,528 | 2014-12-11→2026-06-11 |
| 173 | LEE | living | Communication Services | small/high | 0.70 | 160 | 1990-01-02→2026-06-11 |
| 174 | LFT | living | Real Estate | small/low | 0.38 | 35 | 2013-03-22→2026-06-11 |
| 175 | LITE | living | Technology | large_liquid/low | 0.50 | 3,822 | 2015-07-23→2026-06-11 |
| 176 | LNTH | living | Healthcare | mid/high | 0.66 | 796 | 2015-06-24→2026-06-11 |
| 177 | LQDT | living | Consumer Cyclical | small/high | 0.58 | 348 | 2006-02-23→2026-06-11 |
| 178 | MCO | living | Financials | large_liquid/low | 0.33 | 12,863 | 1990-01-02→2026-06-11 |
| 179 | MDB | living | Technology | large_liquid/high | 0.65 | 13,146 | 2017-10-19→2026-06-11 |
| 180 | MIN | living | Financials | small/low | 0.11 | 223 | 1990-01-02→2026-06-10 |
| 181 | MOH | living | Healthcare | mid/low | 0.43 | 1,669 | 2003-07-02→2026-06-11 |
| 182 | MPX | living | Consumer Cyclical | small/low | 0.53 | 181 | 2001-03-01→2026-05-14 |
| 183 | MRAM | living | Technology | small/high | 0.76 | 122 | 2016-10-07→2026-06-11 |
| 184 | MTG | living | Financials | large_liquid/high | 0.71 | 3,813 | 1991-08-07→2026-06-11 |
| 185 | MVIS | living | Technology | small/high | 0.93 | 132 | 1996-08-27→2026-06-11 |
| 186 | MYND | living | Consumer Defensive | small/high | 0.83 | 49 | 2017-09-27→2026-06-11 |
| 187 | NG | living | Basic Materials | mid/high | 0.70 | 1,302 | 2003-12-02→2026-06-11 |
| 188 | NKTR | living | Healthcare | mid/high | 0.70 | 1,495 | 1994-05-03→2026-06-11 |
| 189 | NMRK | living | Real Estate | large_liquid/high | 0.62 | 1,911 | 2017-12-15→2026-06-11 |
| 190 | NOG | living | Energy | mid/high | 0.90 | 556 | 2007-01-10→2026-06-11 |
| 191 | NVCR | living | Healthcare | large_liquid/high | 0.72 | 4,803 | 2015-10-02→2026-06-11 |
| 192 | OFG | living | Financials | mid/low | 0.48 | 354 | 1990-01-02→2026-06-11 |
| 193 | OFIX | living | Healthcare | mid/low | 0.40 | 632 | 1992-05-18→2026-06-11 |
| 194 | OMER | living | Healthcare | mid/high | 0.84 | 425 | 2009-10-08→2026-06-11 |
| 195 | ONC | living | Healthcare | large_liquid/low | 0.58 | 10,191 | 2016-02-03→2026-06-11 |
| 196 | OPK | living | Healthcare | mid/high | 0.81 | 1,008 | 1995-11-02→2026-06-11 |
| 197 | OPLN | living | Consumer Cyclical | mid/low | 0.35 | 1,745 | 2009-12-11→2026-06-11 |
| 198 | PANL | living | Industrials | small/low | 0.55 | 99 | 2013-12-19→2026-06-11 |
| 199 | ALOY | tail_topup | Basic Materials | small/high | 1.39 | 26 | 2016-08-01→2026-06-10 |
| 200 | CMTO | tail_topup | — | dotcom_2000_2003 | 1.48 | — | 1998-05-22→2003-02-20 |
| 201 | CNVR1 | tail_topup | — | y2011_2015 | 0.97 | — | 1999-01-04→2011-05-06 |
| 202 | EUROY | tail_topup | — | gfc_cycle_2004_2009 | 1.07 | — | 1997-12-31→2007-08-03 |
| 203 | FGEN | tail_topup | Healthcare | y2020_plus | 0.91 | 44,888 | 2014-11-14→2026-01-09 |
| 204 | FMTIF | tail_topup | — | post_2010 | 1.25 | — | 2000-03-15→2010-04-16 |
| 205 | FNLYQ | tail_topup | — | post_2010 | 1.36 | — | 1997-12-31→2010-01-15 |
| 206 | FSNMQ | tail_topup | — | y2011_2015 | 1.37 | — | 1997-12-31→2011-06-07 |
| 207 | GMGC | tail_topup | — | dotcom_2000_2003 | 1.83 | — | 1999-01-04→2002-09-27 |
| 208 | HSGX | tail_topup | — | y2016_2019 | 1.27 | — | 2014-12-03→2019-09-27 |
| 209 | LKCO1 | tail_topup | — | y2016_2019 | 1.36 | — | 2010-05-17→2018-09-19 |
| 210 | TPLQ | tail_topup | — | gfc_cycle_2004_2009 | 1.95 | — | 1999-01-04→2004-05-24 |
| 211 | WEI | tail_topup | — | y2020_plus | 1.34 | — | 2018-11-15→2022-05-18 |