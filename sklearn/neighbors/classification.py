"""Nearest Neighbor Classification"""

# Authors: Jake Vanderplas <vanderplas@astro.washington.edu>
#          Fabian Pedregosa <fabian.pedregosa@inria.fr>
#          Alexandre Gramfort <alexandre.gramfort@inria.fr>
#          Sparseness support by Lars Buitinck <L.J.Buitinck@uva.nl>
#
# License: BSD, (C) INRIA, University of Amsterdam

import numpy as np
from scipy import stats
from ..utils.extmath import weighted_mode

from .base import \
    _check_weights, _get_weights, \
    _check_class_prior, _get_class_prior, \
    NeighborsBase, KNeighborsMixin,\
    RadiusNeighborsMixin, SupervisedIntegerMixin
from ..base import ClassifierMixin
from ..utils import atleast2d_or_csr


class KNeighborsClassifier(NeighborsBase, KNeighborsMixin,
                           SupervisedIntegerMixin, ClassifierMixin):
    """Classifier implementing the k-nearest neighbors vote.

    Parameters
    ----------
    n_neighbors : int, optional (default = 5)
        Number of neighbors to use by default for :meth:`k_neighbors` queries.

    weights : str or callable
        weight function used in prediction.  Possible values:

        - 'uniform' : uniform weights.  All points in each neighborhood
          are weighted equally.
        - 'distance' : weight points by the inverse of their distance.
          in this case, closer neighbors of a query point will have a
          greater influence than neighbors which are further away.
        - [callable] : a user-defined function which accepts an
          array of distances, and returns an array of the same shape
          containing the weights.

        Uniform weights are used by default.

    class_prior : str, list or ndarray, optional (default = 'default')
        class prior probabilities used in prediction. Possible values:

        - 'default': default prior probabilities. For each class, its
          prior probability is the proportion of points in the dataset
          that are in this class.
        - 'flat': equiprobable prior probabilites. If there are C classes,
          then the prior probability for every class is 1/C.
        - [list or ndarray]: a used-defined list or ndarray, listing
          the prior class probability for each class, in increasing order
          of class label.

    algorithm : {'auto', 'ball_tree', 'kd_tree', 'brute'}, optional
        Algorithm used to compute the nearest neighbors:

        - 'ball_tree' will use :class:`BallTree`
        - 'kd_tree' will use :class:`scipy.spatial.cKDtree`
        - 'brute' will use a brute-force search.
        - 'auto' will attempt to decide the most appropriate algorithm
          based on the values passed to :meth:`fit` method.

        Note: fitting on sparse input will override the setting of
        this parameter, using brute force.

    leaf_size : int, optional (default = 30)
        Leaf size passed to BallTree or cKDTree.  This can affect the
        speed of the construction and query, as well as the memory
        required to store the tree.  The optimal value depends on the
        nature of the problem.

    warn_on_equidistant : boolean, optional.  Defaults to True.
        Generate a warning if equidistant neighbors are discarded.
        For classification or regression based on k-neighbors, if
        neighbor k and neighbor k+1 have identical distances but
        different labels, then the result will be dependent on the
        ordering of the training data.
        If the fit method is ``'kd_tree'``, no warnings will be generated.

    p: integer, optional (default = 2)
        Parameter for the Minkowski metric from
        sklearn.metrics.pairwise.pairwise_distances. When p = 1, this is
        equivalent to using manhattan_distance (l1), and euclidean_distance
        (l2) for p = 2. For arbitrary p, minkowski_distance (l_p) is used.

    Examples
    --------
    >>> X = [[0], [1], [2], [3]]
    >>> y = [0, 0, 1, 1]
    >>> from sklearn.neighbors import KNeighborsClassifier
    >>> neigh = KNeighborsClassifier(n_neighbors=3)
    >>> neigh.fit(X, y) # doctest: +ELLIPSIS
    KNeighborsClassifier(...)
    >>> print(neigh.predict([[1.1]]))
    [0]
    >>> print(neigh.predict_proba([[0.9]]))
    [[ 0.66666667  0.33333333]]
    >>> neigh = KNeighborsClassifier(n_neighbors=3, class_prior=[0.75, 0.25])
    >>> neigh.fit(X, y) # doctest: +ELLIPSIS
    KNeighborsClassifier(...)
    >>> print(neigh.predict_proba([[2.0]]))
    [[ 0.6  0.4]]

    See also
    --------
    RadiusNeighborsClassifier
    KNeighborsRegressor
    RadiusNeighborsRegressor
    NearestNeighbors

    Notes
    -----
    See :ref:`Nearest Neighbors <neighbors>` in the online documentation
    for a discussion of the choice of ``algorithm`` and ``leaf_size``.

    http://en.wikipedia.org/wiki/K-nearest_neighbor_algorithm
    
    References
    ----------
    Bishop, Christopher M. *Pattern Recognition and Machine Learning*.
        New York: Springer, 2006, p. 124-7.
    """

    def __init__(self, n_neighbors=5,
                 weights='uniform',
                 class_prior='default',
                 algorithm='auto', leaf_size=30,
                 warn_on_equidistant=True, p=2):
        self._init_params(n_neighbors=n_neighbors,
                          algorithm=algorithm,
                          leaf_size=leaf_size,
                          warn_on_equidistant=warn_on_equidistant,
                          p=p)
        self.weights = _check_weights(weights)
        self.class_prior = _check_class_prior(class_prior)

    def predict(self, X):
        """Predict the class labels for the provided data

        Parameters
        ----------
        X: array
            A 2-D array representing the test points.

        Returns
        -------
        labels: array
            List of class labels (one for each data sample).
        """
        probabilities = self.predict_proba(X)
        return self._classes[probabilities.argmax(axis=1)].astype(np.int)

    def predict_proba(self, X):
        """Return probability estimates for the test data X.

        Parameters
        ----------
        X: array, shape = (n_samples, n_features)
            A 2-D array representing the test points.

        Returns
        -------
        probabilities : array, shape = [n_samples, n_classes]
            Probabilities of the samples for each class in the model,
            where classes are ordered arithmetically.
        """
        X = atleast2d_or_csr(X)

        neigh_dist, neigh_ind = self.kneighbors(X)
        pred_indices = self._y[neigh_ind]

        weights = _get_weights(neigh_dist, self.weights)

        if weights is None:
            weights = np.ones_like(pred_indices)

        probabilities = np.zeros((X.shape[0], self._classes.size))

        # a simple ':' index doesn't work right
        all_rows = np.arange(X.shape[0])

        for i, idx in enumerate(pred_indices.T):  # loop is O(n_neighbors)
            probabilities[all_rows, idx] += weights[:, i]

        # Compute the unnormalized posterior probability, taking
        # self.class_prior_ into consideration.
        class_count = np.bincount(self._y)
        class_prior = _get_class_prior(self._y, self.class_prior)
        probabilities = (probabilities / class_count) * class_prior

        # normalize 'votes' into real [0,1] probabilities
        probabilities = (probabilities.T / probabilities.sum(axis=1)).T
        return probabilities


class RadiusNeighborsClassifier(NeighborsBase, RadiusNeighborsMixin,
                                SupervisedIntegerMixin, ClassifierMixin):
    """Classifier implementing a vote among neighbors within a given radius

    Parameters
    ----------
    radius : float, optional (default = 1.0)
        Range of parameter space to use by default for :meth`radius_neighbors`
        queries.

    weights : str or callable
        weight function used in prediction.  Possible values:

        - 'uniform' : uniform weights.  All points in each neighborhood
          are weighted equally.
        - 'distance' : weight points by the inverse of their distance.
          in this case, closer neighbors of a query point will have a
          greater influence than neighbors which are further away.
        - [callable] : a user-defined function which accepts an
          array of distances, and returns an array of the same shape
          containing the weights.

        Uniform weights are used by default.

    class_prior : str, list or ndarray, optional (default = 'default')
        class prior probabilities used in prediction. Possible values:

        - 'default': default prior probabilities. For each class, its
          prior probability is the proportion of points in the dataset
          that are in this class.
        - 'flat': equiprobable prior probabilites. If there are C classes,
          then the prior probability for every class is 1/C.
        - [list or ndarray]: a used-defined list or ndarray, listing
          the prior class probability for each class, in increasing order
          of class label.

    algorithm : {'auto', 'ball_tree', 'kd_tree', 'brute'}, optional
        Algorithm used to compute the nearest neighbors:

        - 'ball_tree' will use :class:`BallTree`
        - 'kd_tree' will use :class:`scipy.spatial.cKDtree`
        - 'brute' will use a brute-force search.
        - 'auto' will attempt to decide the most appropriate algorithm
          based on the values passed to :meth:`fit` method.

        Note: fitting on sparse input will override the setting of
        this parameter, using brute force.

    leaf_size : int, optional (default = 30)
        Leaf size passed to BallTree or cKDTree.  This can affect the
        speed of the construction and query, as well as the memory
        required to store the tree.  The optimal value depends on the
        nature of the problem.

    p: integer, optional (default = 2)
        Parameter for the Minkowski metric from
        sklearn.metrics.pairwise.pairwise_distances. When p = 1, this is
        equivalent to using manhattan_distance (l1), and euclidean_distance
        (l2) for p = 2. For arbitrary p, minkowski_distance (l_p) is used.

    outlier_label: int, optional (default = None)
        Label, which is given for outlier samples (samples with no
        neighbors on given radius).
        If set to None, ValueError is raised, when outlier is detected.

    Examples
    --------
    >>> X = [[0], [1], [2], [3]]
    >>> y = [0, 0, 1, 1]
    >>> from sklearn.neighbors import RadiusNeighborsClassifier
    >>> neigh = RadiusNeighborsClassifier(radius=1.0)
    >>> neigh.fit(X, y) # doctest: +ELLIPSIS
    RadiusNeighborsClassifier(...)
    >>> print(neigh.predict([[1.5]]))
    [0]
    >>> neigh = RadiusNeighborsClassifier(radius=1.0, class_prior=[0.2, 0.8])
    >>> neigh.fit(X, y) # doctest: +ELLIPSIS
    RadiusNeighborsClassifier(...)
    >>> print(neigh.predict([[1.5]]))
    [1]

    See also
    --------
    KNeighborsClassifier
    RadiusNeighborsRegressor
    KNeighborsRegressor
    NearestNeighbors

    Notes
    -----
    See :ref:`Nearest Neighbors <neighbors>` in the online documentation
    for a discussion of the choice of ``algorithm`` and ``leaf_size``.

    http://en.wikipedia.org/wiki/K-nearest_neighbor_algorithm

    References
    ----------
    Bishop, Christopher M. *Pattern Recognition and Machine Learning*.
        New York: Springer, 2006, p. 124-7.
    """

    def __init__(self, radius=1.0, weights='uniform', class_prior=None,
                 algorithm='auto', leaf_size=30, p=2, outlier_label=None):
        self._init_params(radius=radius,
                          algorithm=algorithm,
                          leaf_size=leaf_size,
                          p=p)
        self.weights = _check_weights(weights)
        self.class_prior = _check_class_prior(class_prior)
        self.outlier_label = outlier_label

    def predict(self, X):
        """Predict the class labels for the provided data

        Parameters
        ----------
        X: array
            A 2-D array representing the test points.

        Returns
        -------
        labels: array
            List of class labels (one for each data sample).
        """
        X = atleast2d_or_csr(X)

        neigh_dist, neigh_ind = self.radius_neighbors(X)
        pred_labels = [self._y[ind] for ind in neigh_ind]

        outliers = []  # row indices of the outliers (if any)
        if self.outlier_label:
            for i, pl in enumerate(pred_labels):
                # Check that all have at least 1 neighbor
                if len(pl) < 1:
                    # We'll impose the label for that row later.
                    outliers.append(i)
        else:
            for pl in pred_labels:
                # Check that all have at least 1 neighbor
                if len(pl) < 1:
                    raise ValueError('no neighbors found for a test sample, '
                                     'you can try using larger radius, '
                                     'give a label for outliers, '
                                     'or consider removing them in your '
                                     'dataset')

        weights = _get_weights(neigh_dist, self.weights)
        if weights is None:
            # `neigh_dist` is an array of objects, where each
            # object is a 1D array of indices.
            weights = np.array([np.ones(len(row)) for row in neigh_dist])

        probabilities = np.zeros((X.shape[0], self._classes.size))

        # We cannot vectorize the following because of the way Python handles
        # M += 1: if a predicted index was to occur more than once (for a
        # given tested point), the corresponding element in `probabilities` 
        # would still be incremented only once.
        for i, pi in enumerate(pred_labels):
            if len(pi) < 1:
                continue  # outlier
            # When we support NumPy >= 1.6, we'll be able to simply use:
            # np.bincount(pi, weights, minlength=self._classes.size)
            unpadded_probs = np.bincount(pi, weights[i])
            probabilities[i] = np.append(unpadded_probs,
                                         np.zeros(self._classes.size -
                                                  unpadded_probs.shape[0]))

        # Compute the unnormalized posterior probability, taking
        # self.class_prior_ into consideration.
        class_count = np.bincount(self._y)
        class_prior = _get_class_prior(self._y, self.class_prior)
        probabilities = (probabilities / class_count) * class_prior

        # normalize 'votes' into real [0,1] probabilities
        probabilities = (probabilities.T / probabilities.sum(axis=1)).T
        
        # Predict the class of each row, based on the maximum posterior
        # probability. If needed, correct the predictions for outliers.
        preds = self._classes[probabilities.argmax(axis=1)].astype(np.int)
        if self.outlier_label:
            preds[outliers] = self.outlier_label

        return preds