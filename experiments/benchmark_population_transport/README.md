# Benchmark Population Transport — execution workspace

This branch is an isolated execution workspace for the benchmark-selection/target-population study. It does not alter `main`.

The workflow freezes an OpenML supervised-classification task frame, audits OpenML-CC18 membership and metadata support, recovers public historical TabZilla outcomes, and runs an outcome-rich validation matrix before any new large-scale model training.

Design rule: the target frame is defined independently of CC18's practical curation filters. Small/large, imbalanced, or high-dimensional tasks are not excluded merely because CC18 excluded them. Results are separated into (i) live OpenML population audit, (ii) historical TabZilla validation oracle, and (iii) later fresh-model execution.
