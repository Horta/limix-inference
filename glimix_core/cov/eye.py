from numpy import exp, log, eye

from optimix import Func, Scalar


class EyeCov(Func):
    r"""
    Identity covariance function.

    The mathematical representation is given by f(x₀, x₁), which takes value s when
    x₀ and x₁ are arrays of the same sample and 0 otherwise. Note that it is possible to
    have two different samples for which the arrays x₀ and x₁ are identical. The
    parameter s is the scale of the matrix.

    Example
    -------

    .. doctest::

        >>> from glimix_core.cov import EyeCov
        >>>
        >>> cov = EyeCov()
        >>> cov.scale = 2.5
        >>> cov.dim = 2
        >>> print(cov.value())
        [[2.5 0. ]
         [0.  2.5]]
        >>> g = cov.gradient()
        >>> print(g['logscale'])
        [[2.5 0. ]
         [0.  2.5]]
        >>> cov.name = "I"
        >>> print(cov)
        EyeCov(): I
          scale: 2.5
          dim: 2
    """

    def __init__(self):
        self._logscale = Scalar(0.0)
        Func.__init__(self, "EyeCov", logscale=self._logscale)
        self._logscale.bounds = (-20.0, +10)
        self._I = None

    @property
    def scale(self):
        """
        Scale parameter.
        """
        return exp(self._logscale)

    @scale.setter
    def scale(self, scale):
        from numpy_sugar import epsilon

        scale = max(scale, epsilon.tiny)
        self._logscale.value = log(scale)

    @property
    def dim(self):
        """ Dimension of the matrix, d.

        It corresponds to the number of rows and to the number of columns.
        """
        return self._I.shape[0]

    @dim.setter
    def dim(self, dim):
        self._I = eye(dim)

    def value(self):
        """
        Covariance matrix.

        Returns
        -------
        ndarray
            s⋅I, for scale s and an d×d identity matrix I.
        """
        return self.scale * self._I

    def gradient(self):
        r"""Derivative of the covariance matrix.

        Derivative is taking over log(s), therefore it is equal to s⋅I.

        Returns
        -------
        logscale : ndarray
            s⋅I, for scale s and an d×d identity matrix I.
        """
        return dict(logscale=self.value())

    def __str__(self):
        tname = type(self).__name__
        msg = "{}()".format(tname)
        if self.name is not None:
            msg += ": {}".format(self.name)
        msg += "\n"
        msg += "  scale: {}\n".format(self.scale)
        msg += "  dim: {}".format(self.dim)
        return msg
