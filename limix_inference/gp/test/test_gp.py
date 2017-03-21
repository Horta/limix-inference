from __future__ import division

from numpy import arange
from numpy.random import RandomState
from numpy.testing import assert_allclose

from limix_inference.cov import LinearCov
from limix_inference.gp import GP
from limix_inference.mean import LinearMean, OffsetMean
from optimix import check_grad


def test_gp_value_1():
    random = RandomState(94584)
    N = 50
    X = random.randn(N, 100)
    offset = 0.5

    mean = OffsetMean()
    mean.offset = offset
    mean.fix('offset')
    mean.set_data(arange(N))

    cov = LinearCov()
    cov.scale = 1.0
    cov.set_data((X, X))

    y = random.randn(N)

    gp = GP(y, mean, cov)
    assert_allclose(gp.feed().value(), -153.623791551399108)


def test_gp_value_2():
    random = RandomState(94584)
    N = 50
    X1 = random.randn(N, 3)
    X2 = random.randn(N, 100)

    mean = LinearMean(3)
    mean.set_data(X1)

    cov = LinearCov()
    cov.scale = 1.0
    cov.set_data((X2, X2))

    y = random.randn(N)

    gp = GP(y, mean, cov)
    assert_allclose(gp.feed().value(), -153.091074766)

    mean.effsizes = [3.4, 1.11, -6.1]
    assert_allclose(gp.feed().value(), -178.273116338)


def test_gp_gradient():
    random = RandomState(94584)
    N = 50
    X = random.randn(N, 100)
    offset = 0.5

    mean = OffsetMean()
    mean.offset = offset
    mean.fix('offset')
    mean.set_data(arange(N))

    cov = LinearCov()
    cov.scale = 1.0
    cov.set_data((X, X))

    y = random.randn(N)

    gp = GP(y, mean, cov)

    assert_allclose(check_grad(gp.feed()), 0, atol=1e-5)


def test_gp_maximize():
    random = RandomState(94584)
    N = 50
    X = random.randn(N, 100)
    offset = 0.5

    mean = OffsetMean()
    mean.offset = offset
    mean.fix('offset')
    mean.set_data(arange(N))

    cov = LinearCov()
    cov.scale = 1.0
    cov.set_data((X, X))

    y = random.randn(N)

    gp = GP(y, mean, cov)

    assert_allclose(gp.feed().value(), -153.623791551)
    gp.feed().maximize(progress=False)
    assert_allclose(gp.feed().value(), -79.8992122415)


if __name__ == '__main__':
    __import__('pytest').main([__file__, '-s'])
