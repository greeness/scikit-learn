"""
Robust location and covariance estimators.

Here are implemented estimators that are resistant to outliers.

"""
# Author: Virgile Fritsch <virgile.fritsch@inria.fr>
#
# License: BSD Style.
import warnings
import numpy as np
from scipy import linalg
from scipy.stats import chi2
from . import empirical_covariance, EmpiricalCovariance
from ..utils.extmath import fast_logdet as exact_logdet


###############################################################################
### Minimum Covariance Determinant
#   Implementing of an algorithm by Rousseeuw & Van Driessen described in
#   (A Fast Algorithm for the Minimum Covariance Determinant Estimator,
#   1999, American Statistical Association and the American Society
#   for Quality, TECHNOMETRICS)
###############################################################################
def c_step(X, h, remaining_iterations=30, initial_estimates=None,
           verbose=False):
    """C_step procedure described in [1] aiming at computing the MCD

    [1] A Fast Algorithm for the Minimum Covariance Determinant Estimator,
        1999, American Statistical Association and the American Society
        for Quality, TECHNOMETRICS

    Parameters
    ----------
    X: array-like, shape (n_samples, n_features)
      Data set in which we look for the h observations whose scatter matrix
      has minimum determinant
    h: int, > n_samples / 2
      Number of observations to compute the ribust estimates of location
      and covariance from.
    remaining_iterations: int
      Number of iterations to perform.
      According to Rousseeuw [1], two iterations are sufficient to get close
      to the minimum, and we never need more than 30 to reach convergence.
    initial_estimates: 2-tuple
      Initial estimates of location and shape from which to run the c_step
      procedure:
      - initial_estimates[0]: an initial location estimate
      - initial_estimates[1]: an initial covariance estimate
    verbose: boolean
      Verbose mode

    Returns
    -------
    T: array-like, shape (n_features,)
      Robust location estimates
    S: array-like, shape (n_features, n_features)
      Robust covariance estimates
    H: array-like, shape (n_samples,)
      A mask for the `h` observations whose scatter matrix has minimum
      determinant

    """
    n_samples, n_features = X.shape

    # Initialisation
    if initial_estimates is None:
        # compute initial robust estimates from a random subset
        support = np.zeros(n_samples).astype(bool)
        support[np.random.permutation(n_samples)[:h]] = True
        T = X[support].mean(0)
        S = empirical_covariance(X[support])
    else:
        # get initial robust estimates from the function parameters
        T = initial_estimates[0]
        S = initial_estimates[1]
        # run a special iteration for that case (to get an initial support)
        inv_S = linalg.pinv(S)
        X_centered = X - T
        dist = (np.dot(X_centered, inv_S) * X_centered).sum(1)
        # compute new estimates
        support = np.zeros(n_samples).astype(bool)
        support[np.argsort(dist)[:h]] = True
        T = X[support].mean(0)
        S = empirical_covariance(X[support])
        detS = exact_logdet(S)
    previous_detS = np.inf

    # Iterative procedure for Minimum Covariance Determinant computation
    detS = exact_logdet(S)
    while (detS < previous_detS) and (remaining_iterations > 0):
        # compute a new support from the full data set mahalanobis distances
        inv_S = linalg.pinv(S)
        X_centered = X - T
        dist = (np.dot(X_centered, inv_S) * X_centered).sum(1)
        # save old estimates values
        previous_T = T
        previous_S = S
        previous_detS = detS
        previous_support = support
        # compute new estimates
        support = np.zeros(n_samples).astype(bool)
        support[np.argsort(dist)[:h]] = True
        T = X[support].mean(0)
        S = empirical_covariance(X[support])
        detS = np.log(linalg.det(S))
        # update remaining iterations for early stopping
        remaining_iterations = remaining_iterations - 1

    # Check convergence
    if np.allclose(detS, previous_detS):
        # c_step procedure converged
        if verbose:
            print 'Optimal couple (T,S) found before ending iterations' \
                '(%d left)' % (remaining_iterations)
        results = T, S, detS, support
    elif detS > previous_detS:
        # determinant has increased (should not happen)
        warnings.warn("Warning! detS > previous_detS (%.15f > %.15f)" \
                          % (detS, previous_detS), RuntimeWarning)
        results = previous_T, previous_S, previous_detS, previous_support

    # Check early stopping
    if remaining_iterations == 0:
        if verbose:
            print 'Maximum number of iterations reached'
        detS = exact_logdet(S)
        results = T, S, detS, support

    return results


def select_candidates(X, h, n_trials, select=1, n_iter=30, verbose=False):
    """Finds the best pure subset of observations to compute MCD from it.

    The purpose of this function is to find the best sets of h
    observations with respect to a minimization of their covariance
    matrix determinant. Equivalently, it removes n_samples-h
    observations to construct what we call a pure data set (i.e. not
    containing outliers). The list of the observations of the pure
    data set is referred to as the `support`.

    Starting from a random support, the pure data set is found by the
    c_step procedure introduced by Rousseeuw and Van Driessen in [1].

    [1] A Fast Algorithm for the Minimum Covariance Determinant Estimator,
        1999, American Statistical Association and the American Society
        for Quality, TECHNOMETRICS

    Parameters
    ----------
    X: array-like, shape (n_samples, n_features)
      Data (sub)set in which we look for the h purest observations
    h: int, [(n + p + 1)/2] < h < n
      The number of samples the pure data set must contain.
    select: int, int > 0
      Number of best candidates results to return.
    n_trials: int, nb_trials > 0 or 2-tuple
      Number of different initial sets of observations from which to
      run the algorithm.
      Instead of giving a number of trials to perform, one can provide a
      list of initial estimates that will be used to iteratively run
      c_step procedures. In this case:
      - n_trials[0]: array-like, shape (n_trials, n_features)
        is the list of `n_trials` initial location estimates
      - n_trials[1]: array-like, shape (n_trials, n_features, n_features)
        is the list of `n_trials` initial covariances estimates
    n_iter: int, nb_iter > 0
      Maximum number of iterations for the c_step procedure.
      (2 is enough to be close to the final solution. "Never" exceeds 20)

    See
    ---
    `c_step` function

    Returns
    -------
    best_T: array-like, shape (select, n_features)
      The `select` location estimates computed from the `select` best
      supports found in the data set (`X`)
    best_S: array-like, shape (select, n_features, n_features)
      The `select` covariance estimates computed from the `select`
      best supports found in the data set (`X`)
    best_H: array-like, shape (select, n_samples)
      The `select` best supports found in the data set (`X`)

    """
    n_samples, n_features = X.shape

    if isinstance(n_trials, int):
        run_from_estimates = False
    elif isinstance(n_trials, tuple):
        run_from_estimates = True
        estimates_list = n_trials
        n_trials = estimates_list[0].shape[0]
    else:
        raise Exception('Bad \'n_trials\' parameter (wrong type)')

    # compute `n_trials` location and shape estimates candidates in the subset
    all_T_sub = np.zeros((n_trials, n_features))
    all_S_sub = np.zeros((n_trials, n_features, n_features))
    all_detS_sub = np.zeros(n_trials)
    all_H_sub = np.zeros((n_trials, n_samples)).astype(bool)
    if not run_from_estimates:
        # perform `n_trials` computations from random initial supports
        for j in range(n_trials):
            all_T_sub[j], all_S_sub[j], all_detS_sub[j], all_H_sub[j] = c_step(
                X, h, remaining_iterations=n_iter, verbose=verbose)
    else:
        # perform computations from every given initial estimates
        for j in range(n_trials):
            all_T_sub[j], all_S_sub[j], all_detS_sub[j], all_H_sub[j] = c_step(
                X, h, remaining_iterations=n_iter,
                initial_estimates=(estimates_list[0][j], estimates_list[1][j]),
                verbose=verbose)

    # find the `n_best` best results among the `n_trials` ones
    index_best = np.argsort(all_detS_sub)[:select]
    best_T = all_T_sub[index_best]
    best_S = all_S_sub[index_best]
    best_H = all_H_sub[index_best]

    return best_T, best_S, best_H


def fast_mcd(X, correction="empirical", reweight="rousseeuw"):
    """Estimates the Minimum Covariance Determinant matrix.

    The FastMCD algorithm has been introduced by Rousseuw and Van Driessen
    in "A Fast Algorithm for the Minimum Covariance Determinant Estimator,
    1999, American Statistical Association and the American Society
    for Quality, TECHNOMETRICS".
    The principle is to compute robust estimates and random subsets before
    pooling them into a larger subsets, and finally into the full data set.
    Depending on the size of the initial sample, we have one, two or three
    such computation levels.

    Parameters
    ----------
    X: array-like, shape (n_samples, n_features)
      The data matrix, with p features and n samples.
    reweight: int (0 < reweight < 2)
      Computation of a reweighted estimator:
        - "rousseeuw" (default): Reweight observations using Rousseeuw's
          method (equivalent to deleting outlying observations from the
          data set before computing location and covariance estimates)
        - else: no reweighting
    correction: str
      Improve the covariance estimator consistency at gaussian models
        - "empirical" (default): correction using the empirical correction
          factor suggested by Rousseeuw and Van Driessen in [1]
        - "theoretical": correction using the theoretical correction factor
          derived in [2]
        - else: no correction

    [1] A Fast Algorithm for the Minimum Covariance Determinant Estimator,
        1999, American Statistical Association and the American Society
        for Quality, TECHNOMETRICS
    [2] R. W. Butler, P. L. Davies and M. Jhun,
        Asymptotics For The Minimum Covariance Determinant Estimator,
        The Annals of Statistics, 1993, Vol. 21, No. 3, 1385-1400

    Returns
    -------
    T: array-like, shape (n_features,)
      Robust location of the data
    S: array-like, shape (n_features, n_features)
      Robust covariance of the features
    support: array-like, type boolean, shape (n_samples,)
      a mask of the observations that have been used to compute
      the robust location and covariance estimates of the data set

    """
    X = np.asarray(X)
    if X.ndim <= 1:
        X = X.reshape((-1, 1))
    n_samples, n_features = X.shape

    # minimum breakdown value
    h = int(np.ceil(0.5 * (n_samples + n_features + 1)))

    # 1-dimensional case quick computation
    # (Rousseeuw, P. J. and Leroy, A. M. (2005) References, in Robust
    #  Regression and Outlier Detection, John Wiley & Sons, chapter 4)
    if n_features == 1:
        # find the sample shortest halves
        X_sorted = np.sort(np.ravel(X))
        diff = X_sorted[h:] - X_sorted[:(n_samples - h)]
        halves_start = np.where(diff == np.min(diff))[0]
        # take the middle points' mean to get the robust location estimate
        T = 0.5 * (X_sorted[h + halves_start] + X_sorted[halves_start]).mean()
        support = np.zeros(n_samples).astype(bool)
        support[np.argsort(np.abs(X - T), axis=0)[:h]] = True
        S = np.asarray([[np.var(X[support])]])
        T = np.array([T])

    ### Starting FastMCD algorithm for p-dimensional case
    if (n_samples > 500) and (n_features > 1):
        ## 1. Find candidate supports on subsets
        # a. split the set in subsets of size ~ 300
        n_subsets = n_samples / 300
        n_samples_subsets = n_samples / n_subsets
        samples_shuffle = np.random.permutation(n_samples)
        h_subset = np.ceil(n_samples_subsets * (h / float(n_samples)))
        # b. perform a total of 500 trials
        n_trials_tot = 500
        n_trials = n_trials_tot / n_subsets
        # c. select 10 best (T,S) for each subset
        n_best_sub = 10
        n_best_tot = n_subsets * n_best_sub
        all_best_T = np.zeros((n_best_tot, n_features))
        all_best_S = np.zeros((n_best_tot, n_features, n_features))
        for i in range(n_subsets):
            low_bound = i * n_samples_subsets
            high_bound = low_bound + n_samples_subsets
            current_subset = X[samples_shuffle[low_bound:high_bound]]
            best_T_sub, best_S_sub, _ = select_candidates(
                current_subset, h_subset, n_trials,
                select=n_best_sub, n_iter=2)
            subset_slice = np.arange(i * n_best_sub, (i + 1) * n_best_sub)
            all_best_T[subset_slice] = best_T_sub
            all_best_S[subset_slice] = best_S_sub
        ## 2. Pool the candidate supports into a merged set
        ##    (possibly the full dataset)
        n_samples_merged = min(1500, n_samples)
        h_merged = np.ceil(n_samples_merged * (h / float(n_samples)))
        if n_samples > 1500:
            n_best_merged = 10
        else:
            n_best_merged = 1
        # find the best couples (T,S) on the merged set
        T_merged, S_merged, H_merged = select_candidates(
            X[np.random.permutation(n_samples)[:n_samples_merged]],
            h_merged, n_trials=(all_best_T, all_best_S), select=n_best_merged)
        ## 3. Finally get the overall best (T,S) couple
        if n_samples < 1500:
            # directly get the best couple (T,S)
            T = T_merged[0]
            S = S_merged[0]
            H = H_merged[0]
        else:
            # select the best couple on the full dataset
            T_full, S_full, H_full = select_candidates(
                X, h, n_trials=(T_merged, S_merged), select=1)
            T = T_full[0]
            S = S_full[0]
            H = H_full[0]
    elif n_features > 1:
        ## 1. Find the 10 best couples (T,S) considering two iterations
        n_trials = 30
        n_best = 10
        T_best, S_best, _ = select_candidates(
            X, h, n_trials=n_trials, select=n_best, n_iter=2)
        ## 2. Select the best couple on the full dataset amongst the 10
        T_full, S_full, H_full = select_candidates(
            X, h, n_trials=(T_best, S_best), select=1)
        T = T_full[0]
        S = S_full[0]
        H = H_full[0]

    ## 4. Obtain consistency at Gaussian models
    if correction == "empirical":
        # theoretical correction
        inliers_ratio = h / float(n_samples)
        S_corrected = S * (inliers_ratio) \
            / chi2(n_features + 2).cdf(chi2(n_features).ppf(inliers_ratio))
    elif correction == "theoretical":
        # empirical correction
        X_centered = X - T
        dist = (np.dot(X_centered, linalg.inv(S)) * X_centered).sum(1)
        S_corrected = S * (np.median(dist) / chi2(n_features).isf(0.5))
    else:
        # no correction
        S_corrected = S

    ## 5. Reweight estimate
    if reweight == "rousseeuw":
        X_centered = X - T
        dist = np.sum(
            np.dot(X_centered, linalg.inv(S_corrected)) * X_centered,
            1)
        mask = dist < chi2(n_features).isf(0.025)
        T_reweighted = X[mask].mean(0)
        S_reweighted = empirical_covariance(X[mask])
        support = np.zeros(n_samples).astype(bool)
        support[mask] = True
    else:
        T_reweighted = T
        S_reweighted = S_corrected
        support = H

    return T_reweighted, S_reweighted, support


class MCD(EmpiricalCovariance):
    """Minimum Covariance Determinant (MCD) robust estimator of covariance

    The Minimum Covariance Determinant estimator is a robust estimator
    of a data set's covariance introduced by P.J.Rousseuw in [1].
    The idea is to find a given proportion of "good" observations which
    are not outliers and compute their empirical covariance matrix.
    This empirical covariance matrix is then rescaled to compensate the
    performed selection of observations ("consistency step").
    Having computed the Minimum Covariance Determinant estimator, one
    can give weights to observations according to their Mahalanobis
    distance, leading the a reweighted estimate of the covariance
    matrix of the data set.

    Rousseuw and Van Driessen [2] developed the FastMCD algorithm in order
    to compute the Minimum Covariance Determinant. This algorithm is used
    when fitting an MCD object to data.
    The FastMCD algorithm also computes a robust estimate of the data set
    location at the same time.

    Parameters
    ----------
    store_precision: bool
        Specify if the estimated precision is stored

    Attributes
    ----------
    `location_`: array-like, shape (n_features,)
        Estimated robust location

    `covariance_`: array-like, shape (n_features, n_features)
        Estimated robust covariance matrix

    `precision_`: array-like, shape (n_features, n_features)
        Estimated pseudo inverse matrix.
        (stored only if store_precision is True)

    `support_`: array-like, shape (n_samples,)
        A mask of the observations that have been used to compute
        the robust estimates of location and shape.

    `correction`: str
        Improve the covariance estimator consistency at gaussian models
          - "empirical" (default): correction using the empirical correction
            factor suggested by Rousseeuw and Van Driessen in [2]
          - "theoretical": correction using the theoretical correction factor
            derived in [3]
          - else: no correction

    `reweight`: str
        Computation of a reweighted MCD estimator:
          - "rousseeuw" (default): Reweight observations using Rousseeuw's
            method (equivalent to deleting outlying observations from the
            data set before computing location and covariance estimates)
          - else: no reweighting

    [1] P. J. Rousseeuw. Least median of squares regression. J. Am
        Stat Ass, 79:871, 1984.
    [2] A Fast Algorithm for the Minimum Covariance Determinant Estimator,
        1999, American Statistical Association and the American Society
        for Quality, TECHNOMETRICS
    [3] R. W. Butler, P. L. Davies and M. Jhun,
        Asymptotics For The Minimum Covariance Determinant Estimator,
        The Annals of Statistics, 1993, Vol. 21, No. 3, 1385-1400

    """
    def fit(self, X, assume_centered=False, correction="empirical",
            reweight="rousseeuw"):
        """Fits a Minimum Covariance Determinant with the FastMCD algorithm.

        Parameters
        ----------
        X: array-like, shape = [n_samples, n_features]
          Training data, where n_samples is the number of samples
          and n_features is the number of features.

        assume_centered: Boolean
          If True, the support of robust location and covariance estimates
          is computed, and a covariance estimate is recomputed from it,
          without centering the data.
          Usefull to work with data whose mean is significantly equal to
          zero but is not exactly zero.
          If False, the robust location and covariance are directly computed
          with the FastMCD algorithm without additional treatment.

        Returns
        -------
        self : object
            Returns self.

        """
        location, covariance, support = fast_mcd(
            X, correction=correction, reweight=reweight)
        if assume_centered:
            location = np.zeros(location.shape[0])
            covariance = empirical_covariance(X[support], assume_centered=True)
        self._set_estimates(covariance)
        self.location_ = location
        self.support_ = support
        self.reweight = reweight
        self.correction = correction

        return self
