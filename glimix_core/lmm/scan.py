from __future__ import division

import numpy as np
import numpy.linalg
import scipy as sp
import scipy.stats
from numpy import all as npall
from numpy import sum as _sum
from numpy import min as _min
from numpy import (asarray, clip, dot, empty, errstate, full, inf, isfinite,
                   log, nan_to_num, zeros, pi)
from numpy.linalg import LinAlgError
from numpy_sugar import epsilon
from numpy_sugar.linalg import rsolve, solve
from tqdm import tqdm
from ..util import hsolve

from ..util import wprint
from ..util import log2pi


class FastScanner(object):
    r"""Approximated fast inference over several covariates.

    Specifically, it computes the log of the marginal likelihood

    .. math::

        \log p(\mathbf y)_j = \log \mathcal N\big(~ \mathrm X\mathbf b_j^*
        + \mathbf{m}_j \alpha_j^*,~
        s_j^* (\mathrm K + v \mathrm I) ~\big),

    for optimal :math:`\mathbf b_j`, :math:`\alpha_j`, and :math:`s_j^*`
    values.
    Vector :math:`\mathbf{m}_j` is the candidate defined by the i-th column
    of matrix ``M`` provided to method
    :func:`glimix_core.lmm.FastScanner.fast_scan`.
    Variance :math:`v` is not optimised for performance reasons.
    The method assumes the user has provided a reasonable value for it.

    Notes
    -----
    The implementation requires further explanation as it is somehow obscure.
    Let :math:`\mathrm B_i=\mathrm Q_i\mathrm D_i^{-1}\mathrm Q_i^{\intercal}`
    for :math:`i \in \{0, 1\}` and
    :math:`\mathrm E_j = [\mathrm X;~ \mathbf m_j]`.
    The matrix resulted from
    :math:`\mathrm E_j^{\intercal}\mathrm B_i\mathrm E_j`
    is represented by the attribute ``_ETBE``, and
    four views of such a matrix are given by the attributes ``_XTBX``,
    ``_XTBM``, ``_MTBX``, and ``_MTBM``.
    Those views represent
    :math:`\mathrm X^{\intercal}\mathrm B_i\mathrm X`,
    :math:`\mathrm X^{\intercal}\mathrm B_i\mathbf m_j`,
    :math:`\mathbf m_j^{\intercal}\mathrm B_i\mathrm X`, and
    :math:`\mathbf m_j^{\intercal}\mathrm B_i\mathbf m_j`, respectively.

    Parameters
    ----------
    y : array_like
    Real-valued outcome.
    X : array_like
    Matrix of covariates.
    QS : tuple
    Economic eigendecomposition ``((Q0, Q1), S0)`` of ``K``.
    v : float
    Variance due to iid effect.
    """

    def __init__(self, y, X, QS, v):

        D = [QS[1] + v, v]
        yTQ = [dot(y.T, Q) for Q in QS[0]]
        XTQ = [dot(X.T, Q) for Q in QS[0]]

        yTQDi = [l / r for (l, r) in zip(yTQ, D) if _min(r) > 0]
        yTBy = _sum(_sum(i * i / j) for (i, j) in zip(yTQ, D) if _min(j) > 0)
        yTBX = [dot(i, j.T) for (i, j) in zip(yTQDi, XTQ)]
        XTQDi = [i / j for (i, j) in zip(XTQ, D) if _min(j) > 0]

        self._yTBy = yTBy
        self._yTBX = yTBX
        self._ETBE = ETBE(XTQDi, XTQ)
        self._XTQ = XTQ
        self._yTQDi = yTQDi
        self._XTQDi = XTQDi
        self._scale = None
        self._QS = QS
        self._D = D

    @property
    def _nsamples(self):
        return self._QS[0][0].shape[0]

    def _static_lml(self):
        n = self._nsamples
        p = len(self._D[0])
        static_lml = -n * log2pi - n

        D0 = clip(self._D[0], epsilon.super_tiny, inf)
        static_lml -= _sum(log(D0))

        D1 = clip(self._D[1], epsilon.super_tiny, inf)
        static_lml -= (n - p) * log(D1)
        return static_lml

    def _fast_scan_chunk(self, M):
        M = asarray(M, float)

        if not M.ndim == 2:
            raise ValueError("`M` array must be bidimensional.")

        if not npall(isfinite(M)):
            raise ValueError("One or more variants have non-finite value.")

        MTQ = [dot(M.T, Q) for Q in self._QS[0]]

        yTBM = [dot(i, j.T) for (i, j) in zip(self._yTQDi, MTQ)]
        XTBM = [dot(i, j.T) for (i, j) in zip(self._XTQDi, MTQ)]
        D = self._D
        MTBM = [_sum(i / j * i, 1) for i, j in zip(MTQ, D) if _min(j) > 0]

        nmarkers = M.shape[1]

        lmls = full(nmarkers, self._static_lml())
        effect_sizes = empty(nmarkers)

        if self._ETBE.ncovariates == 1:
            return self._1covariate_loop(
                lmls, effect_sizes, yTBM, XTBM, MTBM)
        else:
            return self._multicovariate_loop(
                lmls, effect_sizes, yTBM, XTBM, MTBM, nmarkers)

    def _multicovariate_loop(self, lmls, effect_sizes, yTBM, XTBM, MTBM,
                             nmarkers):

        ETBE = self._ETBE

        yTBE = [empty(len(i) + 1) for i in self._yTBX]

        for i in range(len(yTBE)):
            yTBE[i][:-1] = self._yTBX[i]

        for i in range(nmarkers):

            for j in range(len(yTBE)):
                yTBE[j][-1] = yTBM[j][i]
                ETBE.XTBM(j)[:] = XTBM[j][:, i]
                ETBE.MTBX(j)[:] = ETBE.XTBM(j)[:]
                ETBE.MTBM(j)[:] = MTBM[j][i]

            A = sum(ETBE.value[j] for j in range(len(yTBE)))
            b = sum(yTBE[j] for j in range(len(yTBE)))

            beta = _solve(A, b)

            effect_sizes[i] = beta[-1]

            p = self._yTBy
            p -= _sum(2 * dot(j, beta) for j in yTBE)
            for j in range(len(yTBE)):
                p += dot(dot(beta, ETBE.value[j]), beta)

            if self._scale is None:
                scale = p / self._nsamples
            else:
                scale = self._scale
                lmls[i] = lmls[i] + self._nsamples
                lmls[i] = lmls[i] - p / scale

            lmls[i] -= self._nsamples * log(max(scale, epsilon.super_tiny))

        lmls /= 2
        return lmls, effect_sizes

    def _1covariate_loop(self, lmls, effect_sizes, yTBM, XTBM, MTBM):

        ETBE = self._ETBE
        sC00 = sum(ETBE.XTBX(i)[0, 0] for i in range(ETBE.size))
        sC01 = sum(XTBM[i][0, :] for i in range(ETBE.size))
        sC11 = sum(MTBM[i] for i in range(ETBE.size))

        sb = sum(self._yTBX[i][0] for i in range(ETBE.size))
        sbm = sum(yTBM[i] for i in range(ETBE.size))

        beta = hsolve(sC00, sC01, sC11, sb, sbm)
        # beta = [nan_to_num(bet) for bet in beta]

        scale = zeros(len(lmls))

        if self._scale is None:
            scale += self._yTBy
            for i in range(ETBE.size):
                scale += - 2 * (
                    self._yTBX[i][0] * beta[0] + yTBM[i] * beta[1])
                scale += beta[0] * (self._ETBE.XTBX(i)[0, 0] * beta[0] +
                                    XTBM[i][0, :] * beta[1])
                scale += beta[1] * (
                    XTBM[i][0, :] * beta[0] + MTBM[i] * beta[1])
            scale /= self._nsamples
        else:
            scale[:] = self._scale
            lmls += self._nsamples
            bla = zeros(len(lmls))
            bla += self._yTBy
            for i in range(ETBE.size):
                bla += - 2 * (
                    self._yTBX[i][0] * beta[0] + yTBM[i] * beta[1])
                bla += beta[0] * (self._ETBE.XTBX(i)[0, 0] * beta[0] +
                                  XTBM[i][0, :] * beta[1])
                bla += beta[1] * (XTBM[i][0, :] * beta[0] + MTBM[i] * beta[1])

            lmls -= bla / scale

        lmls -= self._nsamples * log(clip(scale, epsilon.super_tiny, inf))
        lmls /= 2

        effect_sizes = beta[1]

        return lmls, effect_sizes

    def fast_scan(self, M, verbose=True):
        r"""LML and fixed-effect sizes of each marker.

        If the scaling factor ``s`` is not set by the user via method
        :func:`set_scale`, its optimal value will be found and
        used in the calculation.

        Parameters
        ----------
        M : array_like
        Matrix of fixed-effects across columns.
        verbose : bool, optional
        ``True`` for progress information; ``False`` otherwise.
        Defaults to ``True``.

        Returns
        -------
        array_like
        Log of the marginal likelihoods.
        array_like
        Fixed-effect sizes.
        """

        if not (M.ndim == 2):
            raise ValueError("`M` array must be bidimensional.")
        p = M.shape[1]

        lmls = empty(p)
        effect_sizes = empty(p)

        if verbose:
            nchunks = min(p, 30)
        else:
            nchunks = min(p, 1)

        chunk_size = (p + nchunks - 1) // nchunks

        for i in tqdm(range(nchunks), desc="Scanning", disable=not verbose):
            start = i * chunk_size
            stop = min(start + chunk_size, M.shape[1])

            l, e = self._fast_scan_chunk(M[:, start:stop])

            lmls[start:stop] = l
            effect_sizes[start:stop] = e

        return lmls, effect_sizes

    def null_lml(self):
        r"""Log of the marginal likelihood for the null hypothesis.

        Returns
        -------
        float
        Log of the margina likelihood.
        """
        n = self._nsamples

        ETBE = self._ETBE
        yTBX = self._yTBX

        A = _sum(ETBE.XTBX(i) for i in range(ETBE.size))
        b = _sum(yTBX, axis=0)
        c = self._yTBy
        beta = _solve(A, b)
        sqrdot = c - dot(b, beta)

        lml = self._static_lml()

        if self._scale is None:
            scale = sqrdot / n
        else:
            scale = self._scale
            lml += n
            lml -= sqrdot / scale

        return (lml - n * log(scale)) / 2

    def set_scale(self, scale):
        r"""Set the scaling factor.

        Calling this method disables the automatic scale learning.

        Parameters
        ----------
        scale : float
        Scaling factor.
        """
        self._scale = scale

    def unset_scale(self):
        r"""Unset the scaling factor.

        If called, it enables the scale learning again.
        """
        self._scale = None


class ETBE(object):
    def __init__(self, XTQDi, XTQ):
        n = XTQDi[0].shape[0] + 1

        self._data = [empty((n, n)), empty((n, n))]

        self._data = []
        for i in range(len(XTQDi)):
            data = empty((n, n))
            data[:-1, :-1] = dot(XTQDi[i], XTQ[i].T)
            self._data.append(data)

    @property
    def size(self):
        return len(self._data)

    @property
    def ncovariates(self):
        return self.XTBX(0).shape[0]

    @property
    def value(self):
        return self._data

    def XTBX(self, i):
        return self._data[i][:-1, :-1]

    def XTBM(self, i):
        return self._data[i][:-1, -1]

    def MTBX(self, i):
        return self._data[i][-1, :-1]

    def MTBM(self, i):
        return self._data[i][-1:, -1:]


def _solve(A, y):

    try:
        beta = solve(A, y)
    except LinAlgError:
        try:
            beta = rsolve(A, y)
        except LinAlgError:
            msg = "Could not converge to the optimal"
            msg += " effect-size of one of the candidates."
            msg += " Setting its effect-size to zero."
            wprint(msg)
            beta = zeros(A.shape[0])

    return beta
