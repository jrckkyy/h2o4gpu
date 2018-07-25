/*!
 * Copyright 2017-2018 H2O.ai, Inc.
 * License   Apache License Version 2.0 (see LICENSE for details)
 */
#pragma once
#include <vector>

#include <iostream>
#include <sstream>

#include "cblas/cblas.h"

#define USE_CUDA() 1

template<typename T>
void self_dot(std::vector<T> array_in, int n, int dim,
              std::vector<T>& dots);

void compute_distances(std::vector<double> data_in,
                       std::vector<double> centroids_in,
                       std::vector<double> &pairwise_distances,
                       int n, int dim, int k);

void compute_distances(std::vector<float> data_in,
                       std::vector<float> centroids_in,
                       std::vector<float> &pairwise_distances,
                       int n, int dim, int k);

// Matrix host dev
#define HG_HOSTDEV       __host__   __device__
#define HG_DEV           __device__
#define HG_DEVINLINE     __device__ __forceinline__
#define HG_HOSTDEVINLINE __host__   __device__      __forceinline__

#define h2o4gpu_error(x) error(x, __FILE__, __LINE__);

inline void error(const char* e, const char* file, int line)
{
  std::stringstream ss;
  ss << e << " - " << file << "(" << line << ")";
  //throw error_text;
  std::cerr << ss.str() << std::endl;
  exit(-1);
}

#define h2o4gpu_check(condition, msg) check(condition, msg, __FILE__, __LINE__);

inline void check(bool val, const char* e, const char* file, int line)
{
  if (!val)
  {
    error(e, file, line);
  }
}
