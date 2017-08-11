from ctypes import *
from h2ogpuml.types import cptr
import numpy as np
import sys
from h2ogpuml.libs.kmeans_gpu import GPUlib
from h2ogpuml.libs.kmeans_cpu import CPUlib
from h2ogpuml.solvers.utils import devicecount
from h2ogpuml.util.typechecks import assert_is_type, assert_satisfies


class KMeans(object):
    def __init__(self, n_clusters=10,
                 max_iter=1000, tol=1E-3, gpu_id=0, n_gpus=1,
                 init_from_labels=False, init_labels="randomselect",
                 init_data="randomselect",
                 verbose=0, seed=None, do_checks=1):

        assert_is_type(n_clusters, int)
        assert_is_type(max_iter, int)
        assert_is_type(tol, float)
        assert_is_type(gpu_id, int)
        assert_is_type(n_gpus, int)
        assert_is_type(init_from_labels, bool)
        assert_is_type(init_labels, str)
        assert_is_type(init_data, str)
        assert_is_type(verbose, int)
        assert_is_type(seed, int, None)
        assert_is_type(do_checks, int)

        self._n_clusters = n_clusters
        self._gpu_id = gpu_id
        self.n_gpus, self.deviceCount = devicecount(n_gpus=n_gpus)
        self._max_iter = max_iter
        self.init_from_labels = init_from_labels
        self.init_labels = init_labels
        self.init_data = init_data
        self.tol = tol
        self._did_sklearn_fit = 0
        self.verbose = verbose
        self.do_checks = do_checks

        self.Xnp = None
        self.ynp = None

        self._centroids = None

        self.lib = self._load_lib()

        if seed is None:
            import random
            self.seed = random.randint(0, 32000)
        else:
            self.seed = seed

    def get_params(self):
        params = {'n_clusters': self._n_clusters, 'n_gpus': self.n_gpus,
                  'max_iter': self._max_iter, 'init': 'random',
                  'algorithm': 'auto', 'precompute_distances': True,
                  'tol': self.tol, 'n_jobs': -1,
                  'random_state': self.seed, 'verbose': self.verbose,
                  'copy_x': True}
        return params

    def set_params(self, n_clusters=None, n_gpus=None, max_iter=None, tol=None,
                   random_state=None, verbose=None):
        if n_clusters is not None:
            self._print_set("n_clusters", self._n_clusters, n_clusters)
            self._n_clusters = n_clusters
        if n_gpus is not None:
            self._print_set("n_gpus", self.n_gpus, n_gpus)
            self.n_gpus = n_gpus
        if max_iter is not None:
            self._print_set("max_iter", self._max_iter, max_iter)
            self._max_iter = max_iter
        if random_state is not None:
            self.seed = random_state
        if verbose is not None:
            self.verbose = verbose
        if tol is not None:
            self.tol = tol

    def fit(self, X, y=None):
        Xnp = self._to_np(X)
        ynp = self._to_np(y)

        self._check_data_content("X", Xnp)

        # Cached for sklearn fit
        self.Xnp = Xnp
        rows = np.shape(Xnp)[0]

        if ynp is None:
            ynp = np.random.randint(rows, size=rows) % self._n_clusters

        self._check_data_content("y", ynp)

        ynp = ynp.astype(np.int)
        ynp = np.mod(ynp, self._n_clusters)

        # Cached for sklearn fit
        self.ynp = ynp

        self._fit(Xnp, ynp)

        self._did_sklearn_fit = 0

        return self

    def sklearn_fit(self):
        """Instantiates a scikit-learn model using previously found,
        with fit(), centroids. """

        assert self._centroids is not None, \
            "Centroids are None. Run fit() first."

        if self._did_sklearn_fit == 0:
            self._did_sklearn_fit = 1
            import sklearn.cluster as sk_cluster
            self.sklearn_model = sk_cluster.KMeans(self._n_clusters, max_iter=1,
                                                   init=self._centroids,
                                                   n_init=1)
            self.sklearn_model.fit(self.Xnp, self.ynp)

    def predict(self, X):
        cols, rows = self._validate_centroids(X)

        Xnp = self._to_np(X)
        self._check_data_content("X", Xnp)
        c_data, _ = self._to_cdata(Xnp)
        c_init_from_labels = 0
        c_init_labels = 0
        c_init_data = 0

        c_centroids, _ = self._to_cdata(self._centroids)
        c_res = c_void_p(0)

        lib = self._load_lib()

        data_ord = ord('c' if np.isfortran(Xnp) else 'r')

        if self.double_precision == 0:
            lib.make_ptr_float_kmeans(1, self.verbose, self.seed, self._gpu_id,
                                      self.n_gpus, rows, cols, c_int(data_ord),
                                      self._n_clusters,
                                      self._max_iter, c_init_from_labels,
                                      c_init_labels, c_init_data,
                                      self.tol, c_data, None, c_centroids,
                                      pointer(c_res))
        else:
            lib.make_ptr_double_kmeans(1, self.verbose, self.seed, self._gpu_id,
                                       self.n_gpus, rows, cols,
                                       c_int(data_ord), self._n_clusters,
                                       self._max_iter, c_init_from_labels,
                                       c_init_labels, c_init_data,
                                       self.tol, c_data, None, c_centroids,
                                       pointer(c_res))

        preds = np.fromiter(cast(c_res, POINTER(c_int)), dtype=np.int32,
                            count=rows)
        preds = np.reshape(preds, rows)
        return preds

    def sklearn_predict(self, X):
        """
        Instantiates, if necessary, a scikit-learn model using centroids
        found by running fit() and predicts labels using that model.
        This method always runs on CPU, not on GPUs.
        """

        self._check_data_content("X", X)
        self.sklearn_fit()
        return self.sklearn_model.predict(X)

    def transform(self, X):
        cols, rows = self._validate_centroids(X)

        Xnp = self._to_np(X)
        c_data, c_data_type = self._to_cdata(Xnp)
        c_centroids, _ = self._to_cdata(self._centroids)
        c_res = c_void_p(0)

        lib = self._load_lib()

        data_ord = ord('c' if np.isfortran(Xnp) else 'r')

        if self.double_precision == 0:
            lib.kmeans_transform_float(self.verbose,
                                       self._gpu_id, self.n_gpus,
                                       rows, cols, c_int(data_ord),
                                       c_data, c_centroids,
                                       pointer(c_res))
        else:
            lib.kmeans_transform_double(self.verbose,
                                        self._gpu_id, self.n_gpus,
                                        rows, cols, c_int(data_ord),
                                        c_data, c_centroids,
                                        pointer(c_res))

        transformed = np.fromiter(cast(c_res, POINTER(c_data_type)),
                                  dtype=c_data_type, count=rows * cols)
        transformed = np.reshape(transformed, rows)
        return transformed

    def sklearn_transform(self, X):
        """
        Instantiates, if necessary, a scikit-learn model using centroids
        found by running fit() and transforms matrix X using that model.
        This method always runs on CPU, not on GPUs.
        """

        self._check_data_content("X", X)
        self.sklearn_fit()
        return self.sklearn_model.transform(X)

    def fit_transform(self, X, y):
        L = np.mod(y, self._n_clusters)
        self.fit(X, L)
        return self.transform(X)

    def fit_predict(self, X, y):
        L = np.mod(y, self._n_clusters)
        self.fit(X, L)
        return self.predict(X)
        # FIXME TODO: Still need (http://scikit-learn.org/stable/modules/generated/sklearn.cluster.KMeans.html#sklearn.cluster.KMeans.fit_predict)
        # get_params, score, set_params
        # various parameters like init, algorithm, n_init
        # need to ensure output as desired

    def _fit(self, data, labels):
        data_ord = ord('c' if np.isfortran(data) else 'r')

        if data.dtype == np.float64:
            self._print_verbose(0, "Detected np.float64 data.")
            self.double_precision = 1
            data_ctype = c_double
            data_dtype = np.float64
        elif data.dtype == np.float32:
            if self.verbose > 0:
                print("Detected np.float32 data")
                sys.stdout.flush()
            self.double_precision = 0
            data_ctype = c_float
            data_dtype = np.float32
        else:
            print(
                "Unknown data type, should be either np.float32 or np.float64")
            print(data.dtype)
            sys.stdout.flush()
            return

        c_init_from_labels = 1 if self.init_from_labels else 0

        if self.init_labels == "random":
            c_init_labels = 0
        elif self.init_labels == "randomselect":
            c_init_labels = 1
        else:
            print(
                """
                Unknown init_labels "%s", should be either 
                "random" or "randomselect".
                """ % self.init_labels
            )
            sys.stdout.flush()
            return

        if self.init_data == "random":
            c_init_data = 0
        elif self.init_data == "selectstrat":
            c_init_data = 1
        elif self.init_data == "randomselect":
            c_init_data = 2
        else:
            print(
                """
                Unknown init_data "%s", should be
                "random", "selectstrat" or "randomselect".
                """ % self.init_data
            )
            sys.stdout.flush()
            return

        res = c_void_p(0)
        c_data = cptr(data, dtype=data_ctype)
        c_labels = cptr(labels, dtype=c_int)

        lib = self._load_lib()

        rows = np.shape(data)[0]
        cols = np.shape(data)[1]

        if self.double_precision == 0:
            status = lib.make_ptr_float_kmeans(0, self.verbose, self.seed,
                                               self._gpu_id, self.n_gpus,
                                               rows, cols,
                                               c_int(data_ord), self._n_clusters,
                                               self._max_iter,
                                               c_init_from_labels,
                                               c_init_labels,
                                               c_init_data,
                                               self.tol, c_data, c_labels,
                                               None, pointer(res))
        else:
            status = lib.make_ptr_double_kmeans(0, self.verbose, self.seed,
                                                self._gpu_id, self.n_gpus,
                                                rows, cols,
                                                c_int(data_ord),
                                                self._n_clusters,
                                                self._max_iter,
                                                c_init_from_labels,
                                                c_init_labels,
                                                c_init_data,
                                                self.tol, c_data, c_labels,
                                                None, pointer(res))
        if status:
            raise ValueError('KMeans failed in C++ library.')

        centroids = np.fromiter(cast(res, POINTER(data_ctype)),
                                dtype=data_dtype,
                                count=self._n_clusters * cols)
        centroids = np.reshape(centroids, (self._n_clusters, cols))

        if np.isnan(centroids).any():
            centroids = centroids[~np.isnan(centroids).any(axis=1)]
            print(
                "Removed %d empty centroids" %
                (self._n_clusters - centroids.shape[0])
            )
            self._n_clusters = centroids.shape[0]

        self._centroids = centroids

        return self._centroids

    def _to_cdata(self, data):
        if data.dtype == np.float64:
            print("Detected np.float64 data")
            sys.stdout.flush()
            self.double_precision = 1
            my_ctype = c_double
        elif data.dtype == np.float32:
            print("Detected np.float32 data")
            sys.stdout.flush()
            self.double_precision = 0
            my_ctype = c_float
        else:
            raise ValueError(
                "Unsupported data type %s, "
                "should be either np.float32 or np.float64" % data.dtype
            )
        return cptr(data, dtype=my_ctype), my_ctype

    def _print_verbose(self, level, msg):
        if self.verbose > level:
            print(msg)
            sys.stdout.flush()

    def _print_set(self, param_name, old_val, new_val):
        self._print_verbose(1, "Changing %s from %d to %d." %
                            (param_name, old_val, new_val))

    def _load_lib(self):
        gpu_lib_getter = GPUlib()
        gpu_lib = gpu_lib_getter.get()
        cpu_lib_getter = CPUlib()
        cpu_lib = cpu_lib_getter.get()

        if (self.n_gpus == 0) or (gpu_lib is None) or (self.deviceCount == 0):
            if self.verbose > 0:
                print("\nUsing CPU KMeans solver.\n")
                sys.stdout.flush()
            return cpu_lib
        elif (self.n_gpus > 0) or (cpu_lib is None) or (self.deviceCount == 0):
            if self.verbose > 0:
                print("\nUsing GPU KMeans solver with %d GPUs.\n" % self.n_gpus)
                sys.stdout.flush()
            return gpu_lib
        else:
            raise RuntimeError("Couldn't instantiate KMeans Solver")

    def _check_data_content(self, name, data):
        if self.do_checks == 1:
            assert np.isfinite(data).all(), "%s contains Inf" % name
            assert not np.isnan(data).any(), "%s contains NA" % name

    def _validate_centroids(self, X):
        assert self._centroids is not None, \
            "Centroids are None. Run fit() first."
        rows = np.shape(X)[0]
        cols = np.shape(X)[1]
        centroids_dim = np.shape(self._centroids)[1]
        assert cols == centroids_dim, \
            "The dimension of X [%d] and centroids [%d] is not equal." % \
            (cols, centroids_dim)
        return cols, rows

    @staticmethod
    def _to_np(data):
        import pandas as pd
        return data.values if isinstance(data, pd.DataFrame) else data

    #################### Properties and setters of properties

    @property
    def n_clusters(self):
        return self._n_clusters

    @n_clusters.setter
    def n_clusters(self, value):
        assert_is_type(value, int)
        assert_satisfies(value, value > 0,
                         "Number of clusters must be positive.")
        self._n_clusters = value

    @property
    def gpu_id(self):
        return self._gpu_id

    @gpu_id.setter
    def gpu_id(self, value):
        assert_is_type(value, int)
        assert_satisfies(value, value >= 0,
                         "GPU ID must be non-negative.")
        self._gpu_id = value

    @property
    def max_iter(self):
        return self._max_iter

    @max_iter.setter
    def max_iter(self, value):
        assert_is_type(value, int)
        assert_satisfies(value, value > 0,
                         "Number of maximum iterations must be non-negative.")
        self._max_iter = value

    #################### Free up memory functions
    # TODO check what has to be freed (predictions??).