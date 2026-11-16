------------------------- MODULE M2HistoryLifecycle -------------------------
(***************************************************************************)
(* M2: the CAM-SIMA history-volume lifecycle, per volume x field:          *)
(*   configure -> set_up (override commit) -> [sample* -> write]* with    *)
(* file rollover and filename allocation.  One history volume is modeled; *)
(* fields are abstracted to their accumulate type, their flag_xyfill, and *)
(* whether their source scheme runs unconditionally.  Buffer contents are *)
(* abstracted to sampled/unsampled per output interval.                   *)
(*                                                                         *)
(* The pre-fix protocol (all Fix* constants FALSE) is the code as of      *)
(* CAM-SIMA 27639b49 (still current at model admission); the Fix*         *)
(* constants are the FG-3 protocol changes from the Nov 2026 state-       *)
(* machine audit.  Mut* constants are fault injections admitted only to   *)
(* demonstrate that the liveness companions can fail.                     *)
(*                                                                         *)
(* The full guarantee statement (property / assumptions / checked domain  *)
(* / connection to code / blind spots) is in this directory's README.md.  *)
(***************************************************************************)
EXTENDS Naturals, FiniteSets

CONSTANTS
  InstFields,          \* fields from hist_add_inst_fields: accumulate type
                       \* 'lst' from configure (cam_hist_file.F90:900)
  AvgFields,           \* fields from hist_add_{avg,min,max,var}_fields,
                       \* modeled uniformly as 'avg'
  XYFillFields,        \* fields registered with flag_xyfill=.true.
  AlwaysSampled,       \* fields whose scheme calls history_out_field every
                       \* step; all others are conditional (e.g. dosw)
  OneStepOutput,       \* volume output frequency is 1*nsteps
  WritePeriod,         \* steps between scheduled writes
  MaxFrames,           \* frames per file before rollover closes it
  MaxSteps,            \* model horizon
  CoarseFilenames,     \* filename spec cannot distinguish nearby opens
                       \* (user spec without %s, F-HIST-2 trigger)
  CoarseDiv,           \* opens within one CoarseDiv-step window share a name
  FixRecomputeSplit,   \* FG-3: derive has_* from the committed accumulate
                       \* types at the end of set_up_fields (fixes F-HIST-1)
  FixFillUnsampled,    \* FG-3: zero-sample intervals write _FillValue
                       \* (fixes F-HIST-5)
  FixFilenameRegistry, \* FG-3: run-wide produced-name registry, abort on
                       \* reuse instead of PIO_CLOBBER (fixes F-HIST-2)
  MutAlwaysFill,       \* fault injection: writes emit fill even when sampled
  MutNeverWrites       \* fault injection: scheduled writes never happen

Fields == InstFields \cup AvgFields
Splits == {"inst", "accum"}

ASSUME InstFields \cap AvgFields = {}
ASSUME Fields /= {}
ASSUME XYFillFields \subseteq Fields
ASSUME AlwaysSampled \subseteq Fields
ASSUME WritePeriod >= 1 /\ MaxFrames >= 1 /\ CoarseDiv >= 1
ASSUME MaxSteps >= WritePeriod
ASSUME OneStepOutput => (WritePeriod = 1)

\* 'lst' buffers land in the instantaneous split file, everything else in
\* the accumulated file (cam_hist_file.F90:1811-1824, :2274-2283)
RouteOf(a) == IF a = "lst" THEN "inst" ELSE "accum"

VARIABLES
  phase,          \* "configured" -> "running" (-> "halted" on a guard abort)
  acc,            \* committed accumulate type per field
  hasSplit,       \* define-time predicates has_instantaneous/has_accumulated
  step,
  sampled,        \* field accumulated at least one sample this interval
  defined,        \* field variable exists in the current file set
  filesOpen,
  framesInFile,
  producedNames,  \* file names allocated so far in this run
  writesDone,
  clobbered,      \* a new file name reused a produced name (PIO_CLOBBER)
  wroteUndef,     \* a write emitted an unsampled, non-fill buffer (UB)
  droppedData,    \* a sampled field was skipped by a write (not defined)
  fillWhenSampled \* a sampled field was written as fill instead of data

vars == <<phase, acc, hasSplit, step, sampled, defined, filesOpen,
          framesInFile, producedNames, writesDone, clobbered, wroteUndef,
          droppedData, fillWhenSampled>>

\* Filename abstraction: a name is <<split, time key>>.  A healthy spec
\* (%y-%m-%d-%s) distinguishes every open; a coarse spec collapses opens
\* within a CoarseDiv-step window onto one name.
TimeKey(t) == IF CoarseFilenames THEN t \div CoarseDiv ELSE t

\* Value written for field f given its interval sampling state; mirrors
\* buff_{1d,2d,3d}_value in src/history/buffers/src/hist_buffer.F90@56d9992,
\* which assigns norm_val only when nacc > 0 or flag_xyfill.
WriteValue(f, sampledNow) ==
  IF MutAlwaysFill THEN "fill"
  ELSE IF sampledNow[f] THEN "data"
  ELSE IF (f \in XYFillFields) \/ FixFillUnsampled THEN "fill"
  ELSE "undef"

Init ==
  \* config_configure: has_* from the namelist field-list counts
  \* (cam_hist_file.F90:877-883); inst fields are 'lst' from the start
  /\ phase = "configured"
  /\ acc = [f \in Fields |-> IF f \in InstFields THEN "lst" ELSE "avg"]
  /\ hasSplit = [s \in Splits |->
       IF s = "inst" THEN InstFields /= {} ELSE AvgFields /= {}]
  /\ step = 0
  /\ sampled = [f \in Fields |-> FALSE]
  /\ defined = [f \in Fields |-> FALSE]
  /\ filesOpen = FALSE
  /\ framesInFile = 0
  /\ producedNames = {}
  /\ writesDone = 0
  /\ clobbered = FALSE
  /\ wroteUndef = FALSE
  /\ droppedData = FALSE
  /\ fillWhenSampled = FALSE

\* config_set_up_fields: the 1*nsteps override rewrites accumulate types to
\* 'lst' (cam_hist_file.F90:1066-1070).  Pre-fix, has_* keep their
\* configure-time values; FG-3 recomputes them here, at the single commit
\* point that finalizes the accumulate types.
Setup ==
  /\ phase = "configured"
  /\ acc' = [f \in Fields |-> IF OneStepOutput THEN "lst" ELSE acc[f]]
  /\ hasSplit' = IF FixRecomputeSplit
       THEN [s \in Splits |-> \E f \in Fields : RouteOf(acc'[f]) = s]
       ELSE hasSplit
  /\ phase' = "running"
  /\ UNCHANGED <<step, sampled, defined, filesOpen, framesInFile,
                 producedNames, writesDone, clobbered, wroteUndef,
                 droppedData, fillWhenSampled>>

\* A model step with no scheduled write: schemes run; conditional schemes
\* may or may not sample their fields (subset nondeterminism).
Advance ==
  /\ phase = "running"
  /\ step < MaxSteps
  /\ ((step + 1) % WritePeriod /= 0) \/ MutNeverWrites
  /\ step' = step + 1
  /\ \E S \in SUBSET (Fields \ AlwaysSampled) :
       sampled' = [f \in Fields |->
         sampled[f] \/ (f \in S) \/ (f \in AlwaysSampled)]
  /\ UNCHANGED <<phase, acc, hasSplit, defined, filesOpen, framesInFile,
                 producedNames, writesDone, clobbered, wroteUndef,
                 droppedData, fillWhenSampled>>

\* A step that ends in a scheduled write (history_write_files).  If no file
\* set is open, names are allocated and fields defined first:
\* set_filenames + the duplicate check that skips the volume itself
\* (cam_history.F90:212-230), then define_file creates only the splits
\* whose has_* flag is set (cam_hist_file.F90:1288-1296) and the define
\* loop routes each field by its current accumulate type
\* (cam_hist_file.F90:1811-1824).  The write loop routes identically and
\* clears written buffers (cam_hist_file.F90:2274-2286).
Write ==
  /\ phase = "running"
  /\ step < MaxSteps
  /\ (step + 1) % WritePeriod = 0
  /\ ~MutNeverWrites
  /\ step' = step + 1
  /\ \E S \in SUBSET (Fields \ AlwaysSampled) :
       LET sampledNow == [f \in Fields |->
             sampled[f] \/ (f \in S) \/ (f \in AlwaysSampled)]
           opening == ~filesOpen
           activeSplits == {s \in Splits : hasSplit[s]}
           newNames == {<<s, TimeKey(step + 1)>> : s \in activeSplits}
           collision == opening /\ (newNames \cap producedNames) /= {}
           defNow == IF opening
                     THEN [f \in Fields |-> hasSplit[RouteOf(acc[f])]]
                     ELSE defined
       IN IF collision /\ FixFilenameRegistry
          THEN \* run-wide registry guard: loud abort before the create
            /\ phase' = "halted"
            /\ sampled' = sampledNow
            /\ UNCHANGED <<defined, filesOpen, framesInFile, producedNames,
                           writesDone, clobbered, wroteUndef, droppedData,
                           fillWhenSampled>>
          ELSE
            /\ phase' = "running"
            /\ defined' = defNow
            /\ producedNames' = producedNames \cup
                 (IF opening THEN newNames ELSE {})
            /\ clobbered' = (clobbered \/ (collision /\ ~FixFilenameRegistry))
            /\ wroteUndef' = (wroteUndef \/
                 (\E f \in Fields :
                    defNow[f] /\ WriteValue(f, sampledNow) = "undef"))
            /\ droppedData' = (droppedData \/
                 (\E f \in Fields : ~defNow[f] /\ sampledNow[f]))
            /\ fillWhenSampled' = (fillWhenSampled \/
                 (\E f \in Fields : defNow[f] /\ sampledNow[f]
                                    /\ WriteValue(f, sampledNow) /= "data"))
            \* clear_buffers runs only for fields the write loop visited;
            \* fields routed to a split that is not open are never cleared
            /\ sampled' = [f \in Fields |->
                 IF defNow[f] THEN FALSE ELSE sampledNow[f]]
            /\ writesDone' = writesDone + 1
            /\ LET nf == framesInFile + 1
               IN IF nf >= MaxFrames
                  THEN filesOpen' = FALSE /\ framesInFile' = 0
                  ELSE filesOpen' = TRUE  /\ framesInFile' = nf
  /\ UNCHANGED <<acc, hasSplit>>

Terminated == phase = "halted" \/ (phase = "running" /\ step = MaxSteps)

\* Explicit terminal stutter so a finished run is not a TLC deadlock
Done == Terminated /\ UNCHANGED vars

Next == Setup \/ Advance \/ Write \/ Done

Spec == Init /\ [][Next]_vars /\ WF_vars(Next)

-----------------------------------------------------------------------------
(* Safety invariants *)

TypeOK ==
  /\ phase \in {"configured", "running", "halted"}
  /\ acc \in [Fields -> {"lst", "avg"}]
  /\ hasSplit \in [Splits -> BOOLEAN]
  /\ step \in 0..MaxSteps
  /\ sampled \in [Fields -> BOOLEAN]
  /\ defined \in [Fields -> BOOLEAN]
  /\ filesOpen \in BOOLEAN
  /\ framesInFile \in 0..MaxFrames
  /\ producedNames \subseteq (Splits \X (0..MaxSteps))
  /\ writesDone \in 0..MaxSteps
  /\ clobbered \in BOOLEAN
  /\ wroteUndef \in BOOLEAN
  /\ droppedData \in BOOLEAN
  /\ fillWhenSampled \in BOOLEAN

\* Define-time and write-time predicates derive from one committed
\* accumulate type: each has_* flag holds iff some field routes to that
\* split.  Violated by F-HIST-1 (flags stale after the override) including
\* its empty-split-file symptom on mixed volumes.
SplitFlagsConsistent ==
  phase /= "configured" =>
    \A s \in Splits : hasSplit[s] <=> (\E f \in Fields : RouteOf(acc[f]) = s)

\* Every field of the volume is defined in some created split file while
\* the file set is open.  Violated by F-HIST-1 (field routed to a split
\* whose file was never created is silently skipped).
RoutingComplete == filesOpen => \A f \in Fields : defined[f]

\* A field that accumulated samples is never skipped by a scheduled write.
\* The data-loss face of F-HIST-1.
NoDroppedData == ~droppedData

\* Write implies samples > 0 or _FillValue: no write ever emits a value
\* from an unsampled buffer.  Violated by F-HIST-5.
NoUndefinedData == ~wroteUndef

\* Liveness companion (safety form): an interval that sampled a field
\* writes those values, not fill.  An implementation that always writes
\* fill satisfies NoUndefinedData but fails here (MutAlwaysFill).
SampledDataIsWritten == ~fillWhenSampled

\* A run never produces the same file name twice.  Violated by F-HIST-2
\* (same-volume reuse is unchecked and PIO_CLOBBER truncates).
NoFilenameClobber == ~clobbered

-----------------------------------------------------------------------------
(* Liveness *)

ExpectedWrites == MaxSteps \div WritePeriod

\* Every scheduled write eventually happens: an implementation that never
\* writes fails this (MutNeverWrites).
AllScheduledWritesOccur == <>(writesDone = ExpectedWrites)

=============================================================================
