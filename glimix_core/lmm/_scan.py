import warnings

from numpy import (
    add,
    all,
    asarray,
    atleast_2d,
    clip,
    copyto,
    dot,
    empty,
    full,
    inf,
    isfinite,
    log,
    newaxis,
    zeros,
)
from numpy.linalg import LinAlgError

from .._util import cache, hsolve, log2pi


class FastScanner(object):
    """
    Approximated fast inference over several covariates.

    Specifically, it maximizes the log of the marginal likelihood ::

        log(p(𝐲)ⱼ) = log𝓝(𝐲 | X𝜷ⱼ + Mⱼ𝜶ⱼ, sⱼ(K + vI)),

    over 𝜷ⱼ, 𝜶ⱼ, and sⱼ. Matrix Mⱼ is the candidate defined by the user. Variance v is
    not optimised for performance reasons. The method assumes the user has provided a
    reasonable value for it.

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

    Notes
    -----
    The implementation requires further explanation as it is somehow obscure. Let
    QSQᵀ = K, where QSQᵀ is the eigendecomposition of K. We then have ::

        p(𝐲)ⱼ =  𝓝(Qᵀ𝐲 | QᵀX𝜷ⱼ + QᵀMⱼ𝜶ⱼ, sⱼ(S + vI)).

    Let Dᵢ = (Sᵢ + vI), where Sᵢ is the part of S with positive values. Similarly,
    let Bᵢ = QᵢDᵢ⁻¹Qᵢᵀ for i ϵ {0, 1} and Eⱼ = [X Mⱼ]. The matrix resulted from
    EⱼᵀBᵢEⱼ is represented by the variable ``ETBE``, and four views of such a matrix are
    given by the variables ``XTBX``, ``XTBM``, ``MTBX``, and ``MTBM``. Those views
    represent XᵀBᵢX, XᵀBᵢMⱼ, MⱼᵀBᵢX, and MⱼᵀBᵢMⱼ, respectively.

    Let 𝐛ⱼ = [𝜷ⱼᵀ 𝜶ⱼᵀ]ᵀ. The optimal parameters according to the marginal likelihood
    are given by ::

        (EⱼᵀBEⱼ)𝐛ⱼ = EⱼᵀB𝐲

    and ::

        s = n⁻¹𝐲ᵀB(𝐲 - Eⱼ𝐛ⱼ).
    """

    def __init__(self, y, X, QS, v):

        y = asarray(y, float)
        X = atleast_2d(asarray(X, float).T).T

        if not all(isfinite(y)):
            raise ValueError("Not all values are finite in the outcome array.")

        if not all(isfinite(X)):
            raise ValueError("Not all values are finite in the `X` matrix.")

        if v < 0:
            raise ValueError("Variance has to be non-negative.")

        if not isfinite(v):
            raise ValueError("Variance has to be a finite value..")

        D = []
        if QS[1].size > 0:
            D += [QS[1] + v]
        if QS[1].size < y.shape[0]:
            D += [full(y.shape[0] - QS[1].size, v)]
        yTQ = [dot(y.T, Q) for Q in QS[0] if Q.size > 0]
        XTQ = [dot(X.T, Q) for Q in QS[0] if Q.size > 0]

        yTQDi = [l / r for (l, r) in zip(yTQ, D) if r.min() > 0]
        yTBy = sum([(i * i / j).sum() for (i, j) in zip(yTQ, D) if j.min() > 0])
        yTBX = [dot(i, j.T) for (i, j) in zip(yTQDi, XTQ)]
        XTQDi = [i / j for (i, j) in zip(XTQ, D) if j.min() > 0]

        self._yTBy = yTBy
        self._yTBX = yTBX

        # Used for performing association scan on single variants
        self._ETBE = [_ETBE(i, j) for (i, j) in zip(XTQDi, XTQ)]
        self._yTBE = [_yTBE(i) for i in yTBX]

        self._XTQ = XTQ
        self._yTQDi = yTQDi
        self._XTQDi = XTQDi
        self._scale = None
        self._QS = QS
        self._D = D
        self._X = X
        self._y = y

    @property
    def _nsamples(self):
        return self._QS[0][0].shape[0]

    @property
    def _ncovariates(self):
        return self._X.shape[1]

    @cache
    def _static_lml(self):
        n = self._nsamples
        static_lml = -n * log2pi - n
        static_lml -= sum(_safe_log(D).sum() for D in self._D)
        return static_lml

    def _fast_scan_chunk(self, M):
        from numpy import sum

        M = asarray(M, float)

        if not M.ndim == 2:
            raise ValueError("`M` array must be bidimensional.")

        if not all(isfinite(M)):
            raise ValueError("One or more variants have non-finite value.")

        MTQ = [dot(M.T, Q) for Q in self._QS[0] if Q.size > 0]
        yTBM = [dot(i, j.T) for (i, j) in zip(self._yTQDi, MTQ)]
        XTBM = [dot(i, j.T) for (i, j) in zip(self._XTQDi, MTQ)]
        D = self._D
        MTBM = [sum(i / j * i, 1) for i, j in zip(MTQ, D) if j.min() > 0]

        lmls = full(M.shape[1], self._static_lml())
        effsizes = empty(M.shape[1])
        scales = empty(M.shape[1])

        if self._ncovariates == 1:
            self._1covariate_loop(lmls, effsizes, scales, yTBM, XTBM, MTBM)
        else:
            self._multicovariate_loop(lmls, effsizes, scales, yTBM, XTBM, MTBM)

        return lmls, effsizes, scales

    def _multicovariate_loop(self, lmls, effsizes, scales, yTBM, XTBM, MTBM):
        ETBE = self._ETBE
        yTBE = self._yTBE
        tuple_size = len(yTBE)
        if self._scale is not None:
            scales[:] = self._scale

        for i in range(XTBM[0].shape[1]):

            for j in range(tuple_size):
                yTBE[j].set_yTBM(yTBM[j][i])
                ETBE[j].set_XTBM(XTBM[j][:, [i]])
                ETBE[j].set_MTBM(MTBM[j][i])

            left = add.reduce([j.value for j in ETBE])
            right = add.reduce([j.value for j in yTBE])
            x = _solve(left, right)
            beta = x[:-1][:, newaxis]
            alpha = x[-1:]
            bstar = _bstar_unpack(beta, alpha, self._yTBy, yTBE, ETBE, _bstar_1effect)

            if self._scale is None:
                scales[i] = bstar / self._nsamples
            else:
                lmls[i] += self._nsamples - bstar / scales[i]

            lmls[i] -= self._nsamples * _safe_log(scales[i])
            effsizes[i] = alpha[0]

        lmls /= 2

    def _multicovariate_set_loop(self, yTBM, XTBM, MTBM):
        if self._scale is not None:
            scale = self._scale

        yTBE = [_yTBE(i, j.shape[0]) for (i, j) in zip(self._yTBX, yTBM)]
        for a, b in zip(yTBE, yTBM):
            a.set_yTBM(b)

        set_size = yTBM[0].shape[0]
        ETBE = [_ETBE(i, j, set_size) for (i, j) in zip(self._XTQDi, self._XTQ)]

        for a, b, c in zip(ETBE, XTBM, MTBM):
            a.set_XTBM(b)
            a.set_MTBM(c)

        left = add.reduce([j.value for j in ETBE])
        right = add.reduce([j.value for j in yTBE])
        x = _solve(left, right)

        beta = x[:-set_size]
        alpha = x[-set_size:]
        bstar = _bstar_unpack(beta, alpha, self._yTBy, yTBE, ETBE, _bstar_set)

        lmls = self._static_lml()

        if self._scale is None:
            scale = bstar / self._nsamples
        else:
            lmls += self._nsamples - bstar / scale

        lmls -= self._nsamples * _safe_log(scale)

        lmls /= 2
        effsizes = alpha

        return lmls, effsizes, scale

    def _1covariate_loop(self, lmls, effsizes, scales, yTBM, XTBM, MTBM):
        ETBE = self._ETBE
        yTBX = self._yTBX
        XTBX = [i.XTBX for i in ETBE]
        yTBy = self._yTBy

        A00 = add.reduce([i.XTBX[0, 0] for i in ETBE])
        A01 = add.reduce([i[0, :] for i in XTBM])
        A11 = add.reduce([i for i in MTBM])

        b0 = add.reduce([i[0] for i in yTBX])
        b1 = add.reduce([i for i in yTBM])

        x = hsolve(A00, A01, A11, b0, b1)
        beta = x[0][newaxis, :]
        alpha = x[1]
        bstar = _bstar_1effect(beta, alpha, yTBy, yTBX, yTBM, XTBX, XTBM, MTBM)

        if self._scale is None:
            scales[:] = bstar / self._nsamples
        else:
            scales[:] = self._scale
            lmls += self._nsamples - bstar / scales

        lmls -= self._nsamples * _safe_log(scales)
        lmls /= 2
        effsizes[:] = alpha

    def fast_scan(self, M, verbose=True):
        """
        LML, scale, and fixed-effect size for single-marker scan.

        If the scaling factor ``s`` is not set by the user via method
        :func:`set_scale`, its optimal value will be found.

        Parameters
        ----------
        M : array_like
            Matrix of fixed-effects across columns.
        verbose : bool, optional
            ``True`` for progress information; ``False`` otherwise.
            Defaults to ``True``.

        Returns
        -------
        lmls : ndarray
            Log of the marginal likelihoods.
        effsizes : ndarray
            Fixed-effect sizes.
        """
        from tqdm import tqdm

        if M.ndim != 2:
            raise ValueError("`M` array must be bidimensional.")
        p = M.shape[1]

        lmls = empty(p)
        effsizes = empty(p)
        scales = empty(p)

        if verbose:
            nchunks = min(p, 30)
        else:
            nchunks = min(p, 1)

        chunk_size = (p + nchunks - 1) // nchunks

        for i in tqdm(range(nchunks), desc="Scanning", disable=not verbose):
            start = i * chunk_size
            stop = min(start + chunk_size, M.shape[1])

            l, e, s = self._fast_scan_chunk(M[:, start:stop])

            lmls[start:stop] = l
            effsizes[start:stop] = e
            scales[start:stop] = s

        return lmls, effsizes, scales

    def scan(self, M):
        """
        LML, fixed-effect sizes, and scale of each marker set.

        If the scaling factor ``s`` is not set by the user via method
        :func:`set_scale`, its optimal value will be found and
        used in the calculation.

        Parameters
        ----------
        M : array_like
            Fixed-effects set.

        Returns
        -------
        lml : float
            Log of the marginal likelihood for each set.
        effsizes : ndarray
            Fixed-effect sizes for each set.
        """
        from numpy_sugar.linalg import ddot

        M = asarray(M, float)

        MTQ = [dot(M.T, Q) for Q in self._QS[0] if Q.size > 0]
        yTBM = [dot(i, j.T) for (i, j) in zip(self._yTQDi, MTQ)]
        XTBM = [dot(i, j.T) for (i, j) in zip(self._XTQDi, MTQ)]
        D = self._D
        MTBM = [ddot(i, 1 / j) @ i.T for i, j in zip(MTQ, D) if j.min() > 0]

        return self._multicovariate_set_loop(yTBM, XTBM, MTBM)

    def null_lml(self):
        """
        Log of the marginal likelihood for the null hypothesis.

        It is implemented as ::

            log(p(𝐲)ⱼ) = log𝓝(Diag(√(sⱼD)) | 𝟎, sⱼD).

        Returns
        -------
        lml : float
            Log of the marginal likelihood.
        """
        n = self._nsamples

        ETBE = self._ETBE
        yTBX = self._yTBX

        A = sum(i.XTBX for i in ETBE)
        b = sum(yTBX)
        beta = _solve(A, b)
        sqrdot = self._yTBy - dot(b, beta)

        lml = self._static_lml()

        if self._scale is None:
            scale = sqrdot / n
        else:
            scale = self._scale
            lml += n
            lml -= sqrdot / scale

        return (lml - n * log(scale)) / 2

    def set_scale(self, scale):
        """
        Set the scaling factor.

        Calling this method disables the automatic scale learning.

        Parameters
        ----------
        scale : float
            Scaling factor.
        """
        self._scale = scale

    def unset_scale(self):
        """
        Unset the scaling factor.

        If called, it enables the scale learning again.
        """
        self._scale = None


class _yTBE:
    def __init__(self, yTBX, set_size=1):
        n = yTBX.shape[0] + set_size
        self._data = empty((n,))
        self._data[:-set_size] = yTBX
        self._m = set_size

    @property
    def value(self):
        return self._data

    @property
    def yTBX(self):
        return self._data[: -self._m]

    @property
    def yTBM(self):
        return self._data[-self._m :]

    def set_yTBM(self, yTBM):
        copyto(self.yTBM, yTBM)


class _ETBE:
    def __init__(self, XTQDi, XTQ, set_size=1):
        n = XTQDi.shape[0] + set_size
        self._data = empty((n, n))
        self._data[:-set_size, :-set_size] = dot(XTQDi, XTQ.T)
        self._m = set_size

    @property
    def value(self):
        return self._data

    @property
    def XTBX(self):
        return self._data[: -self._m, : -self._m]

    @property
    def XTBM(self):
        return self._data[: -self._m, -self._m :]

    @property
    def MTBX(self):
        return self._data[-self._m :, : -self._m]

    @property
    def MTBM(self):
        return self._data[-self._m :, -self._m :]

    def set_XTBM(self, XTBM):
        copyto(self.XTBM, XTBM)
        copyto(self.MTBX, XTBM.T)

    def set_MTBM(self, MTBM):
        copyto(self.MTBM, MTBM)


def _bstar_1effect(beta, alpha, yTBy, yTBX, yTBM, XTBX, XTBM, MTBM):
    """
    Same as :func:`_bstar_set` but for single-effect.
    """
    from numpy_sugar.linalg import dotd
    from numpy import add, sum

    r = full(MTBM[0].shape[0], yTBy)
    r -= 2 * add.reduce([dot(i, beta) for i in yTBX])
    r -= 2 * add.reduce([i * alpha for i in yTBM])
    r += add.reduce([dotd(beta.T, dot(i, beta)) for i in XTBX])
    r += add.reduce([dotd(beta.T, i * alpha) for i in XTBM])
    r += add.reduce([sum(alpha * i * beta, axis=0) for i in XTBM])
    r += add.reduce([alpha * i.ravel() * alpha for i in MTBM])
    return r


def _bstar_set(beta, alpha, yTBy, yTBX, yTBM, XTBX, XTBM, MTBM):
    """
    Compute -2𝐲ᵀBEⱼ𝐛ⱼ + (𝐛ⱼEⱼ)ᵀBEⱼ𝐛ⱼ.

    For 𝐛ⱼ = [𝜷ⱼᵀ 𝜶ⱼᵀ]ᵀ.
    """
    from numpy import add

    r = yTBy
    r -= 2 * add.reduce([i @ beta for i in yTBX])
    r -= 2 * add.reduce([i @ alpha for i in yTBM])
    r += add.reduce([beta.T @ i @ beta for i in XTBX])
    r += 2 * add.reduce([beta.T @ i @ alpha for i in XTBM])
    r += add.reduce([alpha.T @ i @ alpha for i in MTBM])
    return r


def _bstar_unpack(beta, alpha, yTBy, yTBE, ETBE, bstar):
    yTBX = [j.yTBX for j in yTBE]
    yTBM = [j.yTBM for j in yTBE]
    XTBX = [j.XTBX for j in ETBE]
    XTBM = [j.XTBM for j in ETBE]
    MTBM = [j.MTBM for j in ETBE]
    return bstar(beta, alpha, yTBy, yTBX, yTBM, XTBX, XTBM, MTBM)


def _solve(A, y):
    from numpy_sugar.linalg import rsolve

    try:
        beta = rsolve(A, y)
    except LinAlgError:
        msg = "Could not converge to the optimal"
        msg += " effect-size of one of the candidates."
        msg += " Setting its effect-size to zero."
        warnings.warn(msg, RuntimeWarning)
        beta = zeros(A.shape[0])

    return beta


def _safe_log(x):
    from numpy_sugar import epsilon

    return log(clip(x, epsilon.small, inf))
