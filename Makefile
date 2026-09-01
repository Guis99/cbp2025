# /*
# 
# Copyright (c) 2019, North Carolina State University
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
# 
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 
# 3. The names “North Carolina State University”, “NCSU” and any trade-name, personal name,
# trademark, trade device, service mark, symbol, image, icon, or any abbreviation, contraction or
# simulation thereof owned by North Carolina State University must not be used to endorse or promote products derived from this software without prior written permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
# 
# */
# 
# // Author: Eric Rotenberg (ericro@ncsu.edu)

INCLDIR = -I..
CC = g++
OPT = -O3
LIBS = -lcbp -lz
#FLAGS = -std=c++11 -L./lib $(LIBS) $(OPT)
FLAGS = -std=c++20 -L./lib $(LIBS) $(OPT) $(INCLDIR)
CPPFLAGS = -std=c++20 $(OPT) 


OBJ = cond_branch_predictor_interface.o my_cond_branch_predictor.o
# Rebuild the interface object whenever any of the predictor headers change.
# (predictor_params.h / predictors.h / etc. live one level up; parameters.h in lib.)
DEPS = cbp.h my_cond_branch_predictor.h \
       ../predictor_params.h ../predictors.h ../tage_improved.h ../primitives.h \
       ../collect.h lib/parameters.h

DEBUG=0
ifeq ($(DEBUG), 1)
	CC += -ggdb3
endif

# COLLECT=1 enables the COLLECT_DATA instrumentation (windowed time-series to
# a file per run; see collect.h). Distinct from TAGE_STATS. Use `make clean`
# when toggling, since make doesn't track flag changes.
COLLECT=0
ifeq ($(COLLECT), 1)
	FLAGS += -DCOLLECT_DATA
endif


.PHONY: clean lib

all: cbp

lib:
	make -C $@ DEBUG=$(DEBUG)

cbp: $(OBJ) lib/libcbp.a
	$(CC) $(FLAGS) -o $@ $(OBJ)

lib/libcbp.a: lib

%.o: %.cc $(DEPS)
	$(CC) $(FLAGS) -c -o $@ $<


clean:
	rm -f *.o cbp
	make -C lib clean
