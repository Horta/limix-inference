import pytest
import scipy.stats as st
from numpy import array, concatenate, exp, eye, inf, nan, ones, sqrt, zeros
from numpy.random import RandomState
from numpy.testing import assert_allclose
from numpy_sugar.linalg import economic_qs, economic_qs_linear
from scipy.optimize import minimize

from glimix_core._util import assert_interface
from glimix_core.cov import EyeCov, LinearCov, SumCov
from glimix_core.lik import DeltaProdLik
from glimix_core.lmm import LMM, FastScanner
from glimix_core.mean import OffsetMean
from glimix_core.random import GGPSampler


def test_fast_scanner_redundant_candidates():
    random = RandomState(9458)
    n = 10
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0

    y = _outcome_sample(random, offset, X)

    QS = economic_qs_linear(X)

    M = ones((n, 5))
    lmm = LMM(y, M, QS, restricted=False)

    lmm.fit(verbose=False)

    markers = M.copy()

    scanner = lmm.get_fast_scanner()

    scanner.fast_scan(markers, verbose=False)[0]


def test_fast_scanner_set_scale_1covariate():
    random = RandomState(9458)
    n = 10
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0

    y = _outcome_sample(random, offset, X)

    QS = economic_qs_linear(X)

    M = random.randn(n, 1)
    lmm = LMM(y, M, QS)

    lmm.fit(verbose=False)
    assert_allclose(lmm.scale, 5.282731934070453)
    assert_allclose(lmm.delta, 0.7029974630034005)
    assert_allclose(lmm.beta, [0.0599712498212])

    markers = M.copy() + random.randn(n, 1)

    scanner = lmm.get_fast_scanner()
    lmls, eff0, eff1, scales = scanner.fast_scan(markers, verbose=False)

    assert_allclose(lmls, [-21.509721], rtol=1e-6)
    assert_allclose(eff0, [[-1.43206379971882]])
    assert_allclose(eff1, [1.412239], rtol=1e-6)
    assert_allclose(scales, [0.8440354018505616], rtol=1e-6)

    beta = lmm.beta
    assert_allclose(scanner.fast_scan(zeros((10, 1)), verbose=False)[1][0], beta)


def test_fast_scanner_set_scale_1covariate_redundant():
    random = RandomState(9458)
    n = 10
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0

    y = _outcome_sample(random, offset, X)

    QS = economic_qs_linear(X)

    M = random.randn(n, 1)
    lmm = LMM(y, M, QS)

    lmm.fit(verbose=False)

    markers = M.copy()

    scanner = lmm.get_fast_scanner()
    lmls, eff0, eff1, scales = scanner.fast_scan(markers, verbose=False)
    assert_allclose(lmls[0], -22.357525517597185, rtol=1e-6)
    assert_allclose(eff0, [[0.029985622694805182]])
    assert_allclose(eff1[0], 0.02998562491058301, rtol=1e-6, atol=1e-6)
    assert_allclose(scales, [1.0], rtol=1e-6)


def test_fast_scanner_set_scale_multicovariates():
    random = RandomState(9458)
    n = 10
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0

    y = _outcome_sample(random, offset, X)

    QS = economic_qs_linear(X)

    M = random.randn(n, 3)
    lmm = LMM(y, M, QS)

    lmm.fit(verbose=False)

    markers = M.copy()

    scanner = lmm.get_fast_scanner()
    lmls, eff0, eff1, scales = scanner.fast_scan(markers, verbose=False)

    want = [-19.318845, -19.318845, -19.318845]
    assert_allclose(lmls, want, rtol=1e-6, atol=1e-6)

    assert_allclose(
        eff0[2],
        [-0.6923007382350215, 2.3550810825973034, -0.38157769653894497],
        rtol=1e-5,
    )

    want = [-0.34615, 1.177541, -0.381578]
    assert_allclose(eff1, want, rtol=1e-6, atol=1e-6)
    assert_allclose(scales, [1.0, 1.0, 1.0])


def test_lmm_scan_difficult_settings_offset():
    y = array([-1.0449132, 1.15229426, 0.79595129])
    low_rank_K = array([[5.0, 14.0, 23.0], [14.0, 50.0, 86.0], [23.0, 86.0, 149.0]])
    full_rank_K = array([[6.0, 14.0, 23.0], [14.0, 51.0, 86.0], [23.0, 86.0, 150.0]])
    low_rank_QS = economic_qs(low_rank_K)
    full_rank_QS = economic_qs(full_rank_K)
    X = ones((3, 1))

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, low_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [-2.9605947323337506e-16, 0.0], atol=1e-6)
    assert_allclose(lmls, [28.896466, 28.896466], rtol=1e-6, atol=1e-6)
    assert_allclose(eff0, [[3.008011016293077], [-12.837513658497771]])
    assert_allclose(eff1, [-5.5851957509459353, -9.2375605785935715])

    X = ones((3, 1))
    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, low_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.00476137752581085, 0.012358877799161524], atol=1e-6)
    assert_allclose(lmls, [0.823505300549, -0.607251148058])
    assert_allclose(eff0, [[0.3495610486128161], [0.21723441738440089]])
    assert_allclose(eff1, [-1.79486991632, 0.872439001906])

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, low_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.010459203921428906, 0.0], atol=1e-6)
    assert_allclose(lmls, [8.704135, 28.896466], rtol=1e-6)
    assert_allclose(eff0, [[-0.9261322100000001], [-12.837513658497771]])
    assert_allclose(eff1[1], -9.23756057859)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, low_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.49332480112228455, 0.012358877799161524], atol=1e-6)
    assert_allclose(lmls, [-6.137441, -0.607251], rtol=1e-6, atol=1e-6)
    assert_allclose(eff0, [[-0.9093206621461191], [0.21723441738440089]])
    assert_allclose(eff1[1], 0.872439001906)

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, full_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.004736354793149378, 0.012301930830306581], atol=1e-6)
    assert_allclose(lmls, [0.636421389625, -0.795311239268])
    assert_allclose(eff0, [[0.355188079803773], [0.2224382967889082]])
    assert_allclose(eff1, [-1.79757295968, 0.871806031702])

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, full_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.004662840142176661, 0.012134195778553977], atol=1e-6)
    assert_allclose(lmls, [0.251547678451, -1.18305656511])
    assert_allclose(eff0, [[0.3717198167493795], [0.2377661184233066]])
    assert_allclose(eff1, [-1.80551427016, 0.86994164292])

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, full_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.3725256920525814, 0.012301930830306581], atol=1e-6)
    assert_allclose(lmls, [-5.911136, -0.795311], atol=1e-6, rtol=1e-6)
    assert_allclose(eff0, [[-0.9038187010303032], [0.2224382967889082]])
    assert_allclose(eff1[1], 0.871806031702)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, full_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(scales, [0.21713469123194049, 0.012134195778553977], atol=1e-6)
    assert_allclose(lmls, [-5.509792, -1.183057], atol=1e-6, rtol=1e-6)
    assert_allclose(eff0, [[-0.8876088873393126], [0.2377661184233066]])
    assert_allclose(eff1[1], 0.86994164292)


def test_lmm_scan_difficult_settings_multicovariates():
    y = array([-1.0449132, 1.15229426, 0.79595129])
    low_rank_K = array([[5.0, 14.0, 23.0], [14.0, 50.0, 86.0], [23.0, 86.0, 149.0]])
    full_rank_K = array([[6.0, 14.0, 23.0], [14.0, 51.0, 86.0], [23.0, 86.0, 150.0]])
    low_rank_QS = economic_qs(low_rank_K)
    full_rank_QS = economic_qs(full_rank_K)
    X = array(
        [
            [-0.40592765, 1.04348945],
            [0.92275415, -0.32394197],
            [-0.98197991, 1.22912219],
        ]
    )

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, low_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [28.896466, 28.896466], atol=1e-6, rtol=1e-6)
    assert_allclose(
        eff0,
        [
            [-2.247703714834354, 0.8190282920748556],
            [-3.1760541039273127, 0.40265319454969883],
        ],
    )
    assert_allclose(eff1, [-1.195493, 0.318417], atol=1e-6, rtol=1e-6)
    assert_allclose(scales, [1.850371707708594e-17, 1.3877787807814457e-17], atol=1e-6)

    X = ones((3, 1))
    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, low_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [0.823505300549, -0.607251148058])
    assert_allclose(eff0, [[0.3495610486128161], [0.21723441738440089]])
    assert_allclose(eff1, [-1.79486991632, 0.872439001906])
    assert_allclose(scales, [0.00476137752581085, 0.012358877799161524], atol=1e-6)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, low_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [8.704135, 28.896466])
    assert_allclose(eff0, [[-0.9261322100000001], [-12.837513658497771]])
    assert_allclose(eff1[1], -9.23756057859)
    assert_allclose(scales, [0.010459203921428906, 0.0], atol=1e-6)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, low_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [-6.137441, -0.607251], atol=1e-6, rtol=1e-6)
    assert_allclose(eff0, [[-0.9093206621461191], [0.21723441738440089]])
    assert_allclose(eff1[1], 0.872439001906)
    assert_allclose(scales, [0.49332480112228455, 0.012358877799161524], atol=1e-6)

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, full_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [0.636421389625, -0.795311239268])
    assert_allclose(eff1, [-1.79757295968, 0.871806031702])
    assert_allclose(scales, [0.004736354793149378, 0.012301930830306581], atol=1e-6)

    M = array(
        [[0.88766985, -1.80940339], [0.00822629, -0.4488265], [0.55807272, -2.00868376]]
    )
    scanner = FastScanner(y, X, full_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [0.251547678451, -1.18305656511])
    assert_allclose(eff0, [[0.3717198167493795], [0.2377661184233066]])
    assert_allclose(eff1, [-1.80551427016, 0.86994164292])
    assert_allclose(scales, [0.004662840142176661, 0.012134195778553977], atol=1e-6)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, full_rank_QS, 0)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [-5.911136, -0.795311], atol=1e-6, rtol=1e-6)
    assert_allclose(eff0, [[-0.9038187010303032], [0.2224382967889082]])
    assert_allclose(eff1[1], 0.871806031702)
    assert_allclose(scales, [0.3725256920525814, 0.012301930830306581], atol=1e-6)

    M = array([[0.0, -1.80940339], [0.0, -0.4488265], [0.0, -2.00868376]])
    scanner = FastScanner(y, X, full_rank_QS, 0.75)
    lmls, eff0, eff1, scales = scanner.fast_scan(M, verbose=False)
    assert_allclose(lmls, [-5.509792, -1.183057], atol=1e-6, rtol=1e-6)
    assert_allclose(eff0, [[-0.8876088873393126], [0.2377661184233066]])
    assert_allclose(eff1, [0.0, 0.8699416429204303])
    assert_allclose(scales, [0.21713469123194049, 0.012134195778553977], atol=1e-6)


def _outcome_sample(random, offset, X):
    n = X.shape[0]
    mean = OffsetMean(n)
    mean.offset = offset

    cov_left = LinearCov(X)
    cov_left.scale = 1.5

    cov_right = EyeCov(n)
    cov_right.scale = 1.5

    cov = SumCov([cov_left, cov_right])

    lik = DeltaProdLik()

    return GGPSampler(lik, mean, cov).sample(random)


def _covariates_sample(random, n, p):
    X = random.randn(n, p)
    X -= X.mean(0)
    X /= X.std(0)
    X /= sqrt(X.shape[1])
    return X


def test_lmm_scan_lmm_iid_prior():
    random = RandomState(9458)
    n = 30
    X = _covariates_sample(random, n, n + 1)
    markers = random.randn(n, 2)

    offset = 1.0

    y = _outcome_sample(random, offset, X)

    lmm = LMM(y, ones((n, 1)), None)

    lmm.fit(verbose=False)
    scanner = lmm.get_fast_scanner()
    lmls = scanner.fast_scan(markers, verbose=False)[0]
    assert_allclose(lmls[:2], [-63.16019973550036, -62.489358539276715])


def test_lmm_scan_interface():
    y = array([-1.0449132, 1.15229426, 0.79595129])
    low_rank_K = array([[5.0, 14.0, 23.0], [14.0, 50.0, 86.0], [23.0, 86.0, 149.0]])
    QS = economic_qs(low_rank_K)
    X = ones((3, 1))

    y[0] = nan
    with pytest.raises(ValueError):
        FastScanner(y, X, QS, 0.5)

    y[0] = inf
    with pytest.raises(ValueError):
        FastScanner(y, X, QS, 0.5)

    y[0] = 1
    X[0, 0] = nan
    with pytest.raises(ValueError):
        FastScanner(y, X, QS, 0.5)

    y[0] = 1
    X[0, 0] = 1
    with pytest.raises(ValueError):
        FastScanner(y, X, QS, -1)

    with pytest.raises(ValueError):
        FastScanner(y, X, QS, nan)


def test_lmm_scan_public_attrs():
    assert_interface(
        FastScanner,
        ["null_lml", "fast_scan", "scan"],
        ["null_beta", "null_beta_covariance", "null_scale"],
    )


def test_lmm_scan():
    random = RandomState(9458)
    n = 30
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0
    y = _outcome_sample(random, offset, X)
    QS = economic_qs_linear(X)
    M0 = random.randn(n, 2)
    M1 = random.randn(n, 2)

    lmm = LMM(y, M0, QS)
    lmm.fit(verbose=False)

    v0 = lmm.v0
    v1 = lmm.v1
    K = v0 * X @ X.T + v1 * eye(n)
    M = concatenate((M0, M1), axis=1)

    def fun(x):
        beta = x[:4]
        scale = exp(x[4])
        return -st.multivariate_normal(M @ beta, scale * K).logpdf(y)

    res = minimize(fun, [0, 0, 0, 0, 0])
    scanner = lmm.get_fast_scanner()
    lml, eff0, eff1, scale = scanner.scan(M1)

    assert_allclose(lml, -res.fun)
    assert_allclose(eff0, res.x[:2], rtol=1e-5)
    assert_allclose(eff1, res.x[2:4], rtol=1e-5)
    assert_allclose(scale, exp(res.x[4]), rtol=1e-5)

    assert_allclose(scanner.null_lml(), -53.805721275578456, rtol=1e-5)
    assert_allclose(
        scanner.null_beta, [0.26521964226797085, 0.4334778669761928], rtol=1e-5
    )
    assert_allclose(
        scanner.null_beta_covariance,
        [
            [0.06302553593799207, 0.00429640179038484],
            [0.004296401790384839, 0.05591392416235412],
        ],
        rtol=1e-5,
    )
    assert_allclose(scanner.null_scale, 1.0)

    assert_allclose(scanner.null_beta, lmm.beta, rtol=1e-5)
    assert_allclose(scanner.null_beta_covariance, lmm.beta_covariance, rtol=1e-5)


def test_lmm_scan_fast_scan():
    random = RandomState(9458)
    n = 30
    X = _covariates_sample(random, n, n + 1)
    offset = 1.0
    y = _outcome_sample(random, offset, X)
    QS = economic_qs_linear(X)
    M0 = random.randn(n, 2)
    M1 = random.randn(n, 2)

    lmm = LMM(y, M0, QS)
    lmm.fit(verbose=False)

    v0 = lmm.v0
    v1 = lmm.v1
    K = v0 * X @ X.T + v1 * eye(n)
    M = concatenate((M0, M1[:, [0]]), axis=1)

    def fun(x):
        beta = x[:3]
        scale = exp(x[3])
        return -st.multivariate_normal(M @ beta, scale * K).logpdf(y)

    res = minimize(fun, [0, 0, 0, 0])
    scanner = lmm.get_fast_scanner()
    lml, eff0, eff1, scales = scanner.fast_scan(M1, verbose=False)

    assert_allclose(lml[0], -res.fun)
    assert_allclose(eff0[0], res.x[:2], rtol=1e-5)
    assert_allclose(eff1[0], res.x[2:3], rtol=1e-5)
    assert_allclose(scales[0], exp(res.x[3]), rtol=1e-5)
