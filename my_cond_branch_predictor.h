#ifndef _PREDICTOR_H_
#define _PREDICTOR_H_

#include <stdlib.h>

// temporary diagnostics; remove this define to strip all instrumentation
#define TAGE_STATS 1

#ifdef TAGE_STATS
#include <unordered_set>
#endif

#include "predictors.h"

class SampleCondPredictor
{
        // TAGEPredictor<max history length, num tagged components>
        //     (idx_width, tag_width, num_comp, L1, ratio)
        // history lengths: L1 * ratio^i for each tagged component
        // NB: tag_width must differ from idx_width — equal widths make the
        // idx and tag CSRs identical, so tag == idx and tags match everything
        TAGEPredictor<320, 7> tage;

#ifdef TAGE_STATS
        std::unordered_set<uint64_t> uniq_pcs;
        uint64_t n_branches = 0;
        uint64_t n_misaligned = 0;   // pc with low 2 bits set
        uint64_t n_over32 = 0;       // pc that doesn't fit in u32
#endif

    public:

        SampleCondPredictor (void) : tage(12, 11, 7, 5, 2.0f)
        {
        }

        void setup()
        {
        }

        void terminate()
        {
#ifdef TAGE_STATS
            printf("==== PC_STATS ====\n");
            printf("dynamic cond branches: %lu\n", n_branches);
            printf("unique cond branch PCs: %lu (bimodal has 4096 entries, banks 4096 x 7)\n", uniq_pcs.size());
            printf("PCs with nonzero low 2 bits: %lu\n", n_misaligned);
            printf("PCs above 32 bits: %lu\n", n_over32);
            tage.print_stats();
#endif
        }

        bool predict (uint64_t seq_no, uint8_t piece, uint64_t PC, const bool tage_pred)
        {
#ifdef TAGE_STATS
            n_branches++;
            uniq_pcs.insert(PC);
            if (PC & 0x3) { n_misaligned++; }
            if (PC >> 32) { n_over32++; }
#endif
            return tage.predict(static_cast<u32>(PC));
        }

        // Called via spec_update immediately after each conditional-branch
        // prediction, in program order, with the resolved direction. Doing the
        // full TAGE update here preserves the strict predict->update interleave
        // TAGEPredictor assumes, so no per-branch state checkpointing is needed.
        void history_update (uint64_t seq_no, uint8_t piece, uint64_t PC, bool taken, uint64_t nextPC)
        {
            tage.update(static_cast<u32>(PC), taken ? BranchResult::TAKEN : BranchResult::NOT_TAKEN);
        }

        void update (uint64_t seq_no, uint8_t piece, uint64_t PC, bool resolveDir, bool predDir, uint64_t nextPC)
        {
        }
};
// =================
// Predictor End
// =================

#endif
static SampleCondPredictor cond_predictor_impl;
