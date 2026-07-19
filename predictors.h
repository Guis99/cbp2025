#pragma once

#include <array>
#include <cassert>
#include <cstdint>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

#include "primitives.h"

class BranchPredictorBase {
public:
    virtual bool predict(u32 pc) = 0;
    virtual void update(u32 pc, BranchResult branch) = 0;
    virtual std::string predictor_name() const = 0;
    virtual ~BranchPredictorBase() = default;

    friend std::ostream& operator<<(std::ostream& os, const BranchPredictorBase& p) {
        return os << p.predictor_name();
    }
};

class BimodalPredictor : public BranchPredictorBase {
    size_t table_size;
    size_t pc_mask;

    std::vector<SatCounter<2>> pred_table;
    size_t get_idx(size_t pc) const {
        return pc & pc_mask;
    }
    public:
        explicit BimodalPredictor(size_t table_size) :
                table_size(1ull << table_size), pc_mask(this->table_size - 1),
                pred_table(this->table_size, SatCounter<2>()) {
        }

        void update(u32 pc, BranchResult branch) override {
            pred_table[get_idx(pc)].update(branch);
        }

        bool predict(u32 pc) override {
            return pred_table[get_idx(pc)].predict();
        }

        std::string predictor_name() const override { return "Bimodal"; }
};

class GSharePredictor : public BranchPredictorBase {
    size_t table_size;
    size_t history_length;
    size_t pc_mask;
    size_t history_mask;

    std::vector<SatCounter<2>> pred_table;
    HistoryBuffer<64> history_buffer;

    public:
        GSharePredictor(size_t table_size, size_t history_length) :
                table_size(1ull << table_size), history_length(1ull << history_length),
                pc_mask(this->table_size - 1), history_mask(this->history_length - 1),
                pred_table(this->table_size, SatCounter<2>()),
                history_buffer() {}

        u64 get_idx(u32 pc) const {
            size_t history_idx = history_buffer.as_idx() & history_mask; // select lower *history_length* bits
            return (pc ^ history_idx) & pc_mask; // canonical gshare idx construction, select lower table_size bits
        }

        void update(u32 pc, BranchResult branch) override {
            pred_table[get_idx(pc)].update(branch);
            history_buffer.update(branch);
        }

        bool predict(u32 pc) override {
            return pred_table[get_idx(pc)].predict();
        }

        std::string predictor_name() const override { return "GShare"; }
};

class GSelectPredictor : public BranchPredictorBase {
    public:
        GSelectPredictor(size_t table_size, size_t history_length) {}

        bool predict(u32 pc) override { return false; }
        void update(u32 pc, BranchResult branch) override {}
        std::string predictor_name() const override { return "GSelect"; }
};

class TwoLevelPredictor : public BranchPredictorBase {
    size_t table_size;
    size_t history_length;
    size_t pc_mask;
    size_t history_mask;

    std::vector<std::vector<SatCounter<2>>> pred_table;
    std::vector<HistoryBuffer<64>> branch_history_table;

    public:
        TwoLevelPredictor(size_t table_size, size_t history_length) :
                table_size(1ull << table_size), history_length(1ull << history_length), 
                pc_mask(this->table_size - 1), history_mask(this->history_length - 1),
                pred_table(this->table_size, std::vector<SatCounter<2>>(1ull << history_length)),
                branch_history_table(this->table_size, HistoryBuffer<64>()) {}

        u64 get_pc_idx(u32 pc) const {
            return pc & pc_mask;
        }

        u64 get_history_idx(size_t history) const {
            return branch_history_table[history].as_idx() & history_mask;
        }

        void update(u32 pc, BranchResult branch) override {
            size_t pc_idx = get_pc_idx(pc);
            size_t history_idx = get_history_idx(pc_idx);

            branch_history_table[pc_idx].update(branch); // update branch history
            pred_table[pc_idx][history_idx].update(branch); // update counter
        }

        bool predict(u32 pc) override {
            size_t pc_idx = get_pc_idx(pc);
            size_t history_idx = get_history_idx(pc_idx);

            return pred_table[pc_idx][history_idx].predict();
        }

        std::string predictor_name() const override { return "TwoLevel"; }
};

template <class Pred1, class Pred2>
class TournamentPredictor : public BranchPredictorBase {
    Pred1& predictor_1;
    Pred2& predictor_2;
    size_t table_size;
    size_t pc_mask;
    std::vector<SatCounter<2>> meta_pred_table;;
    bool last_pred_1 = false;
    bool last_pred_2 = false;
    public:
        TournamentPredictor(Pred1& predictor_1, Pred2& predictor_2, size_t table_size) :
                predictor_1(predictor_1), 
                predictor_2(predictor_2),
                table_size(1ull << table_size), pc_mask(this->table_size - 1),
                meta_pred_table(this->table_size, SatCounter<2>()) {}

        size_t get_idx(size_t pc) const { return pc & pc_mask; }

        void update(u32 pc, BranchResult branch) override {
            size_t pc_idx = get_idx(pc);
            
            bool pred1_correct = last_pred_1 == branch;
            bool pred2_correct = last_pred_2 == branch;

            if (pred1_correct && !pred2_correct) {
                meta_pred_table[pc_idx].update(BranchResult::TAKEN);
            } else if (!pred1_correct && pred2_correct) {
                meta_pred_table[pc_idx].update(BranchResult::NOT_TAKEN);
            }

            predictor_1.update(pc, branch);
            predictor_2.update(pc, branch);
        }

        bool predict(u32 pc) override {
            size_t pc_idx = get_idx(pc);

            last_pred_1 = predictor_1.predict(pc);
            last_pred_2 = predictor_2.predict(pc);

            bool meta_prediction = meta_pred_table[pc_idx].predict();
            if (meta_prediction) {
                return last_pred_1;
            } else {
                return last_pred_2;
            }
        }

        std::string predictor_name() const override { return "Tournament(" + predictor_1.predictor_name() + "," + predictor_2.predictor_name() + ")"; }
};

#define PRINT_ALLOC_DEBUG false

class PerceptronPredictor : public BranchPredictorBase {
    size_t table_size;
    size_t history_length;
    size_t pc_mask;
    size_t history_mask;
    std::vector<Perceptron> pred_table;
    HistoryBuffer<64> history_buffer;

    size_t get_idx(size_t pc) {
        return pc & pc_mask;
    }

    public:
        PerceptronPredictor(size_t table_size, size_t history_length) :
                table_size(1ull << table_size), history_length(history_length),
                pc_mask(this->table_size - 1), history_mask((1ull << history_length) - 1),
                pred_table(this->table_size, Perceptron(history_length)),
                history_buffer() {}

        void update(u32 pc, BranchResult branch) override {
            pred_table[get_idx(pc)].update(branch, history_buffer.as_idx() & history_mask, history_length);
            history_buffer.update(branch);
        }

        bool predict(u32 pc) override {
            return pred_table[get_idx(pc)].predict(history_buffer.as_idx() & history_mask, history_length);
        }

        std::string predictor_name() const override { return "PerceptronPredictor"; }
};

template<int H, int NC>
class TAGEPredictor : public BranchPredictorBase {
    size_t _idx_width;
    size_t _tag_width;
    size_t _table_size;
    size_t _pc_mask;
    size_t _tag_mask;

    HistoryBuffer<H> _history_buffer;
    std::vector<SatCounter<2>> _pred_table;
    std::vector<std::vector<TagEntry>> _banks;

    std::array<csr, 2*NC> _hashes = {};
    std::array<u16, NC> _history_lengths = {};
    std::array<u16, 2*NC> _idx_cache = {};

    size_t _branches_seen = 0;
    int8_t _top_idx = -1;

    bool _alt_on_new = false;
    bool _top_pred = false;
    bool _alt_pred = false;

#ifdef TAGE_STATS
    // temporary diagnostics, slot 0 = bimodal base, slot i+1 = bank i
    std::array<u64, NC+1> _stat_prov_cnt = {};
    std::array<u64, NC+1> _stat_prov_miss = {};
    u64 _stat_total = 0;
    u64 _stat_alt_used = 0, _stat_alt_used_miss = 0, _stat_alt_prov_miss = 0;
    u64 _stat_alloc_attempt = 0, _stat_alloc_success = 0, _stat_resets = 0;
#endif

    size_t _get_idx(size_t pc) {
        return pc & _pc_mask;
    }

    void _allocate_new(bool should_flip) {
        bool allocated = false;
#ifdef TAGE_STATS
        _stat_alloc_attempt++;
#endif
        for (u8 i = _top_idx+1; i < NC; i++) {
            auto b_idx = _idx_cache[i];
            auto b_useful = _banks[i][b_idx].get_u();
            if (b_useful == 0 && !allocated) {
                auto b_tag = _idx_cache[i+NC];
                _banks[i][b_idx].allocate(b_tag, should_flip);
                allocated = true;
#ifdef TAGE_STATS
                _stat_alloc_success++;
#endif
                    
                break;
            }
        }

        if (!allocated) {
            for (u8 i = _top_idx+1; i < NC; i++) {
                auto b_idx = _idx_cache[i];
                _banks[i][b_idx].update_u(BranchResult::NOT_TAKEN);
            }
        }
    }

    void _reset_all_banks() {
#ifdef TAGE_STATS
        _stat_resets++;
#endif
        for (auto& bank : _banks) {
            for (auto& entry : bank) {
                entry.clear();
            }
        }
    }
    
    public:
        TAGEPredictor(size_t idx_width, size_t tag_width, u8 num_comp, u16 L1, float ratio) :
                _idx_width(idx_width), _tag_width(tag_width), 
                _table_size(1ull << idx_width), 
                _pc_mask(_table_size - 1), _tag_mask((1ull << tag_width) - 1),
                _history_buffer(),
                _pred_table(_table_size, SatCounter<2>()), 
                _banks(NC, std::vector<TagEntry>(_table_size, TagEntry()))
            {
                for (int i = 0; i < NC; i++) {
                    if (L1 > H) {
                        char err_msg[50];
                        snprintf(err_msg, 49, "%d is greater than the max history length of %d", L1, H);
                        throw(std::runtime_error(err_msg));
                    }
                    _history_lengths[i] = L1;    
                    _hashes[2*i] = csr(_pc_mask, _idx_width - 1, (L1 - 1) % idx_width);
                    _hashes[2*i+1] = csr(_tag_mask, _tag_width - 1, (L1 - 1) % tag_width);
                    L1 *= ratio;    
                }
        }

        void update(u32 pc, BranchResult branch) override {
            bool provider_corr = _top_pred == branch;
            bool alt_corr = _alt_pred == branch;

#ifdef TAGE_STATS
            _stat_total++;
            const bool final_pred = _alt_on_new ? _alt_pred : _top_pred;
            _stat_prov_cnt[_top_idx+1]++;
            if (final_pred != branch) { _stat_prov_miss[_top_idx+1]++; }
            if (_alt_on_new) {
                _stat_alt_used++;
                if (_alt_pred != branch) { _stat_alt_used_miss++; }
                if (_top_pred != branch) { _stat_alt_prov_miss++; }
            }
#endif
            
            if (!provider_corr && !_alt_on_new) {
                _allocate_new(branch);
            }

            if (_top_idx > -1) {
                auto pred_idx = _idx_cache[_top_idx];
                _banks[_top_idx][pred_idx].update_ctr(branch);
                if (provider_corr && !alt_corr && !_alt_on_new) {
                    _banks[_top_idx][pred_idx].update_u(BranchResult::TAKEN);
                } else if (!provider_corr && alt_corr && !_alt_on_new) {
                    _banks[_top_idx][pred_idx].update_u(BranchResult::NOT_TAKEN);
                }

            } else {
                _pred_table[_get_idx(pc)].update(branch);
            }

            for (int i = 0; i < NC; i++) {
                u16 hist_len = _history_lengths[i];
                bool oldest = _history_buffer.get_bit_at(hist_len-1);

                _hashes[2*i].shift_and_fold(branch, oldest);
                _hashes[2*i+1].shift_and_fold(branch, oldest);
            }

            _history_buffer.update(branch);

            if (_branches_seen++ > 256'000) {
                _reset_all_banks();
                _branches_seen = 0;
            }
        }

        bool predict(u32 pc) override {
            _top_pred = _pred_table[_get_idx(pc)].predict();
            _alt_pred = _top_pred;
            _top_idx = -1;
            _alt_on_new = false;
            for (int i = 0; i < NC; i++) {
                u32 idx_hash = _hashes[2*i].hash;
                u32 tag_hash = _hashes[2*i+1].hash;

                u16 idx = idx_hash ^ (pc & _pc_mask);
                u16 tag = tag_hash ^ (pc & _tag_mask);

                _idx_cache[i] = idx;
                _idx_cache[i+NC] = tag;

                bool pred = _banks[i][idx].predict();
                bool tag_match = _banks[i][idx].match_tag(tag);
                if (tag_match) {
                    _alt_pred = _top_pred;
                    _top_pred = pred;
                    _top_idx = i;
                }
            }

            if (_top_idx > -1) {
                auto top_idx = _idx_cache[_top_idx];
                if (_banks[_top_idx][top_idx].get_u() == 0 && (_banks[_top_idx][top_idx].get_ctr() == 3 || _banks[_top_idx][top_idx].get_ctr() == 4)) {
                    _alt_on_new = true;
                    return _alt_pred;
                }
            }

            return _top_pred;
        }

        std::string predictor_name() const override { return "TAGE"; }

#ifdef TAGE_STATS
        void print_stats() const {
            auto pct = [](u64 num, u64 den) { return den ? 100.0 * num / den : 0.0; };
            std::cout << "==== TAGE_STATS ====\n";
            std::cout << "total updates: " << _stat_total << "\n";
            for (int i = 0; i <= NC; i++) {
                if (i == 0) { std::cout << "bimodal        "; }
                else { std::cout << "bank " << i-1 << " (h=" << _history_lengths[i-1] << ")"; }
                std::cout << ": provided " << _stat_prov_cnt[i]
                          << " (" << pct(_stat_prov_cnt[i], _stat_total) << "%)"
                          << ", final MR " << pct(_stat_prov_miss[i], _stat_prov_cnt[i]) << "%\n";
            }
            std::cout << "alt_on_new used: " << _stat_alt_used
                      << " (" << pct(_stat_alt_used, _stat_total) << "%)"
                      << ", MR when used " << pct(_stat_alt_used_miss, _stat_alt_used) << "%"
                      << " (provider would have had MR " << pct(_stat_alt_prov_miss, _stat_alt_used) << "%)\n";
            std::cout << "alloc attempts: " << _stat_alloc_attempt
                      << ", success " << pct(_stat_alloc_success, _stat_alloc_attempt) << "%"
                      << ", u-resets: " << _stat_resets << "\n";
        }
#endif
};