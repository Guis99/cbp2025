#ifndef _PREDICTOR_H_
#define _PREDICTOR_H_

#include <array>
#include <cstdio>
#include <cstdlib>
#include <memory>
#include <string>

// ========definitions consumed by below headers======== 

#define USE_PHIST_ // turns on path history in tage_improved.h

#include "predictors.h"
#include "tage_improved.h"
#include "predictor_params.h"   // shared geometry (BIM_LOG, GSH_*, TL_*, PCP_*, TP_*, TI_*)
#include "lib/parameters.h"     // PREDICTOR_TYPE, set by cbp.cc's -p flag

static constexpr bool TSCL_64LB_ON = false;

// ================

// nLookups the TAGEImproved template exposes for the given TI_NC.
constexpr int TI_NLOOKUPS = 2 * TI_NC;

static std::array<bool, TI_NLOOKUPS + 1> make_no_skip() {
    std::array<bool, TI_NLOOKUPS + 1> no_skip;
    no_skip.fill(true);
    return no_skip;
}

// Build the predictor selected by -p / PREDICTOR_TYPE, sized from
// predictor_params.h so the swept geometry matches sizing.cpp exactly.
// "reference" returns nullptr; predict() then falls back to the CBP2016
// TAGE-SC-L prediction, giving a free baseline column in the sweep.
static std::unique_ptr<BranchPredictorBase> make_predictor(const std::string& t) {
    if (t == "bimodal")      return std::make_unique<BimodalPredictor>(BIM_LOG);
    if (t == "gshare")       return std::make_unique<GSharePredictor>(GSH_TBL, GSH_HIST);
    if (t == "twolevel")     return std::make_unique<TwoLevelPredictor>(TL_TBL, TL_HIST);
    if (t == "perceptron")   return std::make_unique<PerceptronPredictor>(PCP_TBL, PCP_HIST);
    if (t == "tage")         return std::make_unique<TAGEPredictor<TP_H, TP_NC>>(
                                        TP_IDX, TP_TAG, TP_NC, TP_L1, TP_RATIO);
    if (t == "tageimproved") {
        // SC on/off comes from the TI_SC env var (set per run by scripts/sweep_ti.sh):
        // TI_SC=1 enables the statistical corrector; unset/0 leaves it off (baseline).
        const char* sc_env = std::getenv("TI_SC");
        const bool use_sc = sc_env && std::atoi(sc_env) != 0;
        std::printf("==== TI_SC: %s ====\n", use_sc ? "on" : "off");
        return std::make_unique<TAGEImproved<TI_N_L, TI_N_U, TI_NC>>(
                                        TI_BASE_IW, TI_TAGE_IW, TI_SHORT_TW, TI_LONG_TW,
                                        TI_FIRST_LONG, TI_MIN_HIST, TI_MAX_HIST, make_no_skip(), use_sc);
    }
    if (t == "reference")    return nullptr;   // predict() falls back to tage_pred
    std::fprintf(stderr, "unknown predictor type: '%s'\n", t.c_str());
    std::exit(1);
}

class SampleCondPredictor
{
        std::unique_ptr<BranchPredictorBase> pred;   // null => "reference" baseline

    public:
        // Deferred construction: cond_predictor_impl is a static built before
        // main(), so PREDICTOR_TYPE isn't parsed yet here. Build in setup().
        SampleCondPredictor (void) {}

        void setup()
        {
            pred = make_predictor(PREDICTOR_TYPE);
            // pred = nullptr;
            std::printf("==== PREDICTOR: %s ====\n", PREDICTOR_TYPE.c_str());
        }

        void terminate()
        {
            // if (PREDICTOR_TYPE == "tageimproved") {
            //     static_cast<TAGEImproved<TI_N_L, TI_N_U, TI_NC>>(pred)->print_stats();
            // }
            // pred.reset();
        }

        bool predict (uint64_t seq_no, uint8_t piece, uint64_t PC, const bool tage_pred)
        {
            return pred ? pred->predict(PC) : tage_pred;
        }

        // Called via spec_update immediately after each conditional-branch
        // prediction, in program order, with the resolved direction. Doing the
        // full update here preserves the strict predict->update interleave the
        // predictors assume, so no per-branch state checkpointing is needed.
        void history_update (uint64_t seq_no, uint8_t piece, uint64_t PC, bool taken, uint64_t nextPC)
        {
            if (pred)
                pred->update(PC, taken ? BranchResult::TAKEN : BranchResult::NOT_TAKEN);
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
