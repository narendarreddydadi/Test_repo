# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for tensorflow.kernels.functional_ops."""

import numpy as np

from tensorflow.core.framework import attr_value_pb2
from tensorflow.core.protobuf import config_pb2
from tensorflow.python.client import session
from tensorflow.python.eager import cancellation
from tensorflow.python.eager import context
from tensorflow.python.eager import def_function as eager_def_function
from tensorflow.python.eager import executor
from tensorflow.python.framework import config as framework_config
from tensorflow.python.framework import constant_op
from tensorflow.python.framework import dtypes
from tensorflow.python.framework import errors
from tensorflow.python.framework import function
from tensorflow.python.framework import ops
from tensorflow.python.framework import test_util
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import collective_ops
from tensorflow.python.ops import functional_ops
from tensorflow.python.ops import gen_functional_ops
from tensorflow.python.ops import gradients_impl
from tensorflow.python.ops import init_ops
from tensorflow.python.ops import math_ops
from tensorflow.python.ops import variable_scope
from tensorflow.python.ops import variables
import tensorflow.python.ops.tensor_array_grad  # pylint: disable=unused-import
from tensorflow.python.platform import test


# pylint: disable=invalid-name
def simple_scoped_fn(a, x):
  """Simple function: (a, x) -> 2(x+a), but with "2" as a variable in scope."""
  with variable_scope.variable_scope("body"):
    # Dummy variable, just to check that scoping works as intended.
    two = variable_scope.get_variable(
        "two", [],
        dtype=dtypes.int32,
        initializer=init_ops.constant_initializer(2))
    return math_ops.multiply(math_ops.add(a, x), two)


@test_util.with_control_flow_v2
class FunctionalOpsTest(test.TestCase):

  @test_util.run_in_graph_and_eager_modes
  def testFoldl_Simple(self):
    elems = constant_op.constant([1, 2, 3, 4, 5, 6], name="data")

    r = functional_ops.foldl(
        lambda a, x: math_ops.multiply(math_ops.add(a, x), 2),
        elems)
    self.assertAllEqual(208, self.evaluate(r))

    r = functional_ops.foldl(
        lambda a, x: math_ops.multiply(math_ops.add(a, x), 2),
        elems,
        initializer=10)
    self.assertAllEqual(880, self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testFoldl_SingleInputMultiOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array([1, -1.0])
    r = functional_ops.foldl(lambda a, x: a + x, elems, initializer)
    r_value = self.evaluate(r)

    self.assertAllEqual(22, r_value[0])
    self.assertAllEqual(20, r_value[1])

  @test_util.run_in_graph_and_eager_modes
  def testFoldl_MultiInputSingleOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array(1.0)
    r = functional_ops.foldl(lambda a, x: a + x[0] + x[1], (elems, -elems),
                             initializer)
    self.assertAllEqual(1, self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testFoldl_MultiInputDifferentDimsSingleOutput(self):
    elems = np.array([[1.0, 1.0, 1.0], [2.0, 3.0, 4.0]])
    other_elems = np.array([-1.0, 1.0])
    initializer = np.array([0.0, 0.0, 0.0])
    r = functional_ops.foldl(lambda a, x: a + x[0] * x[1],
                             (elems, other_elems), initializer)
    self.assertAllEqual([1.0, 2.0, 3.0], self.evaluate(r))

  @test_util.run_deprecated_v1
  def testFoldl_Scoped(self):
    with self.cached_session() as sess:
      with variable_scope.variable_scope("root") as varscope:
        elems = constant_op.constant([1, 2, 3, 4, 5, 6], name="data")

        r = functional_ops.foldl(simple_scoped_fn, elems)
        # Check that we have the one variable we asked for here.
        self.assertEqual(len(variables.trainable_variables()), 1)
        self.assertEqual(variables.trainable_variables()[0].name,
                         "root/body/two:0")
        sess.run([variables.global_variables_initializer()])
        self.assertAllEqual(208, self.evaluate(r))

        # Now let's reuse our single variable.
        varscope.reuse_variables()
        r = functional_ops.foldl(simple_scoped_fn, elems, initializer=10)
        self.assertEqual(len(variables.trainable_variables()), 1)
        self.assertAllEqual(880, self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testFoldr_Simple(self):
    elems = constant_op.constant([1, 2, 3, 4, 5, 6], name="data")

    r = functional_ops.foldr(
        lambda a, x: math_ops.multiply(math_ops.add(a, x), 2),
        elems)
    self.assertAllEqual(450, self.evaluate(r))

    r = functional_ops.foldr(
        lambda a, x: math_ops.multiply(math_ops.add(a, x), 2),
        elems,
        initializer=10)
    self.assertAllEqual(1282, self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testFoldr_SingleInputMultiOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array([1, -1.0])
    r = functional_ops.foldr(lambda a, x: a + x, elems, initializer)
    r_value = self.evaluate(r)

    self.assertAllEqual(22, r_value[0])
    self.assertAllEqual(20, r_value[1])

  @test_util.run_in_graph_and_eager_modes
  def testFoldr_MultiInputSingleOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array(1.0)
    r = functional_ops.foldr(lambda a, x: a + x[0] + x[1], (elems, -elems),
                             initializer)
    self.assertAllEqual(1, self.evaluate(r))

  @test_util.run_deprecated_v1
  def testFoldr_Scoped(self):
    with self.cached_session() as sess:
      with variable_scope.variable_scope("root") as varscope:
        elems = constant_op.constant([1, 2, 3, 4, 5, 6], name="data")

        r = functional_ops.foldr(simple_scoped_fn, elems)
        # Check that we have the one variable we asked for here.
        self.assertEqual(len(variables.trainable_variables()), 1)
        self.assertEqual(variables.trainable_variables()[0].name,
                         "root/body/two:0")
        sess.run([variables.global_variables_initializer()])
        self.assertAllEqual(450, self.evaluate(r))

        # Now let's reuse our single variable.
        varscope.reuse_variables()
        r = functional_ops.foldr(simple_scoped_fn, elems, initializer=10)
        self.assertEqual(len(variables.trainable_variables()), 1)
        self.assertAllEqual(1282, self.evaluate(r))

  # pylint: disable=unnecessary-lambda
  @test_util.run_deprecated_v1
  def testFold_Grad(self):
    with self.cached_session():
      elems = constant_op.constant([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], name="data")
      v = constant_op.constant(2.0, name="v")
      r = functional_ops.foldl(
          lambda a, x: math_ops.multiply(a, x), elems, initializer=v)
      r = gradients_impl.gradients(r, v)[0]
      self.assertAllEqual(720.0, self.evaluate(r))

      r = functional_ops.foldr(
          lambda a, x: math_ops.multiply(a, x), elems, initializer=v)
      r = gradients_impl.gradients(r, v)[0]
      self.assertAllEqual(720.0, self.evaluate(r))
  # pylint: enable=unnecessary-lambda

  @test_util.run_in_graph_and_eager_modes
  def testScan_Simple(self):
    elems = constant_op.constant([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], name="data")
    v = constant_op.constant(2.0, name="v")

    # pylint: disable=unnecessary-lambda
    r = functional_ops.scan(lambda a, x: math_ops.multiply(a, x), elems)
    self.assertAllEqual([1., 2., 6., 24., 120., 720.], self.evaluate(r))

    r = functional_ops.scan(
        lambda a, x: math_ops.multiply(a, x), elems, initializer=v)
    self.assertAllEqual([2., 4., 12., 48., 240., 1440.], self.evaluate(r))
    # pylint: enable=unnecessary-lambda

  @test_util.run_in_graph_and_eager_modes
  def testScan_Reverse(self):
    elems = constant_op.constant([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], name="data")
    v = constant_op.constant(2.0, name="v")

    # pylint: disable=unnecessary-lambda
    r = functional_ops.scan(lambda a, x: math_ops.multiply(a, x), elems,
                            reverse=True)
    self.assertAllEqual([720., 720., 360., 120., 30., 6.], self.evaluate(r))
    r = functional_ops.scan(
        lambda a, x: math_ops.multiply(a, x), elems, initializer=v,
        reverse=True)
    self.assertAllEqual([1440., 1440., 720., 240., 60., 12.],
                        self.evaluate(r))
    # pylint: enable=unnecessary-lambda

  @test_util.run_in_graph_and_eager_modes
  def testScan_SingleInputMultiOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = (np.array(1.0), np.array(-1.0))
    r = functional_ops.scan(lambda a, x: (a[0] * x, -a[1] * x), elems,
                            initializer)
    r_value = self.evaluate(r)

    self.assertAllEqual([1.0, 2.0, 6.0, 24.0, 120.0, 720.0], r_value[0])
    self.assertAllEqual([1.0, -2.0, 6.0, -24.0, 120.0, -720.0], r_value[1])

  @test_util.run_in_graph_and_eager_modes
  def testScan_MultiInputSingleOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array(1.0)
    # Multiply a * 1 each time
    r = functional_ops.scan(lambda a, x: a * (x[0] + x[1]),
                            (elems + 1, -elems), initializer)
    self.assertAllEqual([1.0, 1.0, 1.0, 1.0, 1.0, 1.0], self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testScan_MultiInputSameTypeOutput(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    r = functional_ops.scan(lambda a, x: (a[0] + x[0], a[1] + x[1]),
                            (elems, -elems))
    r_value = self.evaluate(r)
    self.assertAllEqual(np.cumsum(elems), r_value[0])
    self.assertAllEqual(np.cumsum(-elems), r_value[1])

  @test_util.run_in_graph_and_eager_modes
  def testScan_MultiOutputMismatchedInitializer(self):
    elems = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    initializer = np.array(1.0)
    # Multiply a * 1 each time
    with self.assertRaisesRegex(
        ValueError, "two structures don't have the same nested structure"):
      functional_ops.scan(lambda a, x: (a, -a), elems, initializer)

  @test_util.run_deprecated_v1
  def testScan_Scoped(self):
    with self.cached_session() as sess:
      with variable_scope.variable_scope("root") as varscope:
        elems = constant_op.constant([1, 2, 3, 4, 5, 6], name="data")

        r = functional_ops.scan(simple_scoped_fn, elems)
        # Check that we have the one variable we asked for here.
        self.assertEqual(len(variables.trainable_variables()), 1)
        self.assertEqual(variables.trainable_variables()[0].name,
                         "root/body/two:0")
        sess.run([variables.global_variables_initializer()])
        results = np.array([1, 6, 18, 44, 98, 208])
        self.assertAllEqual(results, self.evaluate(r))

        # Now let's reuse our single variable.
        varscope.reuse_variables()
        r = functional_ops.scan(simple_scoped_fn, elems, initializer=2)
        self.assertEqual(len(variables.trainable_variables()), 1)
        results = np.array([6, 16, 38, 84, 178, 368])
        self.assertAllEqual(results, self.evaluate(r))

  @test_util.run_in_graph_and_eager_modes
  def testScanFoldl_Nested(self):
    elems = constant_op.constant([1.0, 2.0, 3.0, 4.0], name="data")
    inner_elems = constant_op.constant([0.5, 0.5], name="data")

    def r_inner(a, x):
      return functional_ops.foldl(
          lambda b, y: b * y * x, inner_elems, initializer=a)

    r = functional_ops.scan(r_inner, elems)

    # t == 0 (returns 1)
    # t == 1, a == 1, x == 2 (returns 1)
    #   t_0 == 0, b == a == 1, y == 0.5, returns b * y * x = 1
    #   t_1 == 1, b == 1,      y == 0.5, returns b * y * x = 1
    # t == 2, a == 1, x == 3 (returns 1.5*1.5 == 2.25)
    #   t_0 == 0, b == a == 1, y == 0.5, returns b * y * x = 1.5
    #   t_1 == 1, b == 1.5,    y == 0.5, returns b * y * x = 1.5*1.5
    # t == 3, a == 2.25, x == 4 (returns 9)
    #   t_0 == 0, b == a == 2.25, y == 0.5, returns b * y * x = 4.5
    #   t_1 == 1, b == 4.5,       y == 0.5, returns b * y * x = 9
    self.assertAllClose([1., 1., 2.25, 9.], self.evaluate(r))

  @test_util.run_deprecated_v1
  def testScan_Control(self):
    with self.cached_session() as sess:
      s = array_ops.placeholder(dtypes.float32, shape=[None])
      b = array_ops.placeholder(dtypes.bool)

      with ops.control_dependencies([b]):
        c = functional_ops.scan(lambda a, x: x * a, s)
      self.assertAllClose(
          np.array([1.0, 3.0, 9.0]), sess.run(c, {s: [1, 3, 3],
                                                  b: True}))

  @test_util.run_deprecated_v1
  def testScan_Grad(self):
    with self.cached_session():
      elems = constant_op.constant([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], name="data")
      v = constant_op.constant(2.0, name="v")

      # pylint: disable=unnecessary-lambda
      r = functional_ops.scan(
          lambda a, x: math_ops.multiply(a, x), elems, initializer=v)
      # pylint: enable=unnecessary-lambda
      r = gradients_impl.gradients(r, v)[0]
      self.assertAllEqual(873.0, self.evaluate(r))

  @test_util.run_deprecated_v1
  def testScanGradientWithPartStopGradient(self):
    a = variables.Variable(0.0, name="a")
    b = variables.Variable(0.0, name="b")
    elems = array_ops.zeros(5)
    l0, l1 = functional_ops.scan(
        lambda elem_, input_: (a, b), elems, initializer=(0., 0.))
    loss = l0 + array_ops.stop_gradient(l1)
    grad = gradients_impl.gradients(ys=[loss], xs=[a, b])
    with self.test_session():
      self.evaluate(variables.global_variables_initializer())
      self.evaluate(grad)

  @test_util.run_in_graph_and_eager_modes
  def testFoldShape(self):
    x = constant_op.constant([[1, 2, 3], [4, 5, 6]])

    def fn(_, current_input):
      return current_input

    initializer = constant_op.constant([0, 0, 0])
    y = functional_ops.foldl(fn, x, initializer=initializer)
    self.assertAllEqual(y.get_shape(), self.evaluate(y).shape)

  @test_util.run_in_graph_and_eager_modes
  def testScanShape(self):
    x = constant_op.constant([[1, 2, 3], [4, 5, 6]])

    def fn(_, current_input):
      return current_input

    initializer = constant_op.constant([0, 0, 0])
    y = functional_ops.scan(fn, x, initializer=initializer)
    self.assertAllEqual(y.get_shape(), self.evaluate(y).shape)

  # TODO(akshayka): this test fails in eager: the iterable is of length 0 so
  # so the body of the while loop never executes
  @test_util.run_deprecated_v1
  def testScanEmptyTensor(self):
    with self.cached_session():
      x = functional_ops.scan(
          lambda x, _: x, math_ops.range(0), initializer=array_ops.ones([2, 4]))
      self.assertAllEqual([0, 2, 4], x.get_shape())
      self.assertAllEqual(x.get_shape(), self.evaluate(x).shape)

  @test_util.run_deprecated_v1
  def testScanUnknownShape(self):
    x = array_ops.placeholder(dtypes.float32)
    initializer = array_ops.placeholder(dtypes.float32)

    def fn(_, current_input):
      return current_input

    y = functional_ops.scan(fn, x, initializer=initializer)
    self.assertIs(None, y.get_shape().dims)

  @test_util.run_deprecated_v1
  def testScanVaryingShape(self):
    with self.cached_session() as sess:
      x = array_ops.placeholder(dtype=dtypes.float32, shape=[None, 2])
      x_t = array_ops.transpose(x)
      # scan over dimension 0 (with shape None)
      result = functional_ops.scan(lambda a, x: a + x, x)
      # scanned over transposed dimension 0 (with shape 2)
      result_t = functional_ops.scan(lambda a, x: a + x, x_t, infer_shape=False)
      # ensure gradients can be calculated
      result_grad = gradients_impl.gradients(result, [x])[0]
      result_t_grad = gradients_impl.gradients(result_t, [x_t])[0]

      # smoke test to ensure they all evaluate
      sess.run([result, result_t, result_grad, result_t_grad],
               feed_dict={x: [[1.0, 2.0]]})

  @test_util.run_deprecated_v1
  def testRemoteFunction(self):
    worker_config = config_pb2.ConfigProto()
    worker_config.device_count["CPU"] = 2
    worker, _ = test_util.create_local_cluster(
        1, 1, worker_config=worker_config)

    @function.Defun(dtypes.int32, dtypes.int32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/job:ps/task:0"):
      a = variables.Variable(2, dtype=dtypes.int32)
      b = variables.Variable(3, dtype=dtypes.int32)

    with ops.device("/job:worker/replica:0/task:0/cpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b],
          Tout=[dtypes.int32],
          f=_remote_fn,
          target="/job:worker/replica:0/task:0/cpu:1")

    with session.Session(worker[0].target) as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, [6])

  @test_util.run_deprecated_v1
  def testRemoteFunctionDirectSession(self):
    worker_config = config_pb2.ConfigProto()
    worker_config.device_count["CPU"] = 2

    @function.Defun(dtypes.int32, dtypes.int32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/job:localhost/replica:0/task:0/cpu:0"):
      a = variables.Variable(2, dtype=dtypes.int32)
      b = variables.Variable(3, dtype=dtypes.int32)

    with ops.device("/job:localhost/replica:0/task:0/cpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b],
          Tout=[dtypes.int32],
          f=_remote_fn,
          target="/job:localhost/replica:0/task:0/cpu:1")

    with self.test_session(config=worker_config) as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, [6])

  @test_util.run_deprecated_v1
  def testRemoteFunctionSameDeviceDirectSession(self):

    @function.Defun(dtypes.int32, dtypes.int32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/cpu:0"):
      a = variables.Variable(2, dtype=dtypes.int32)
      b = variables.Variable(3, dtype=dtypes.int32)

    with ops.device("/cpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b], Tout=[dtypes.int32], f=_remote_fn, target="/cpu:0")

    with self.cached_session() as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, [6])

  @test_util.run_deprecated_v1
  def testRemoteFunctionCPUGPU(self):
    if not test_util.is_gpu_available():
      self.skipTest("No GPU available")

    @function.Defun(dtypes.float32, dtypes.float32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/job:localhost/replica:0/task:0/cpu:0"):
      a = variables.Variable(2, dtype=dtypes.float32)
      b = variables.Variable(3, dtype=dtypes.float32)

    with ops.device("/job:localhost/replica:0/task:0/cpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b],
          Tout=[dtypes.float32],
          f=_remote_fn,
          target="/job:localhost/replica:0/task:0/device:GPU:0")[0] + 3.0

    with self.cached_session() as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, 9.0)

  @test_util.run_deprecated_v1
  def testRemoteFunctionGPUCPU(self):
    if not test_util.is_gpu_available():
      self.skipTest("No GPU available")

    @function.Defun(dtypes.float32, dtypes.float32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/job:localhost/replica:0/task:0/device:GPU:0"):
      a = variables.Variable(2, dtype=dtypes.float32)
      b = variables.Variable(3, dtype=dtypes.float32)

    with ops.device("/job:localhost/replica:0/task:0/device:GPU:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b],
          Tout=[dtypes.float32],
          f=_remote_fn,
          target="/job:localhost/replica:0/task:0/cpu:0")[0] + 3.0

    with self.cached_session() as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, 9.0)

  @test_util.run_deprecated_v1
  def testRemoteFunctionGPUCPUStrings(self):
    if not test_util.is_gpu_available():
      self.skipTest("No GPU available")

    @function.Defun(dtypes.string)
    def _remote_fn(inp):
      return array_ops.identity(inp)

    a = array_ops.constant("a")

    with ops.device("/gpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a], Tout=[dtypes.string], f=_remote_fn, target="/cpu:0")

    with self.cached_session() as sess:
      ret = self.evaluate(remote_op)
      self.assertAllEqual(ret, [b"a"])

  @test_util.run_deprecated_v1
  def testRemoteFunctionCrossProcess(self):
    workers, _ = test_util.create_local_cluster(2, 1)

    @function.Defun(dtypes.float32, dtypes.float32)
    def _remote_fn(a, b):
      return math_ops.multiply(a, b)

    with ops.device("/job:ps/task:0"):
      a = variables.Variable(2, dtype=dtypes.float32)
      b = variables.Variable(3, dtype=dtypes.float32)

    with ops.device("/job:worker/replica:0/task:0/cpu:0"):
      remote_op = functional_ops.remote_call(
          args=[a, b],
          Tout=[dtypes.float32],
          f=_remote_fn,
          target="/job:worker/replica:0/task:1/cpu:0")[0] + 3.0

    with session.Session(workers[0].target) as sess:
      self.evaluate(variables.global_variables_initializer())
      mul = self.evaluate(remote_op)
      self.assertEqual(mul, 9)

  @test_util.run_v2_only
  def testRemoteFunctionCancellation(self):
    context._reset_context()
    logical_devices = []
    logical_devices.append(context.LogicalDeviceConfiguration())
    logical_devices.append(context.LogicalDeviceConfiguration())
    framework_config.set_logical_device_configuration(
        framework_config.list_physical_devices("CPU")[0], logical_devices)

    @function.Defun(dtypes.float32)
    def _remote_fn(v):
      # We run two collectives here to make sure we cancel in the middle of the
      # RemoteCall. The second one should never finish.
      anchor = collective_ops.all_reduce_v2(
          v, group_size=2, group_key=1, instance_key=1)
      with ops.control_dependencies([anchor]):
        return collective_ops.all_reduce_v2(
            v, group_size=2, group_key=1, instance_key=2)

    @eager_def_function.function
    def run():
      with ops.device("/cpu:0"):
        return functional_ops.remote_call(
            args=[constant_op.constant([1.])] + _remote_fn.captured_inputs,
            Tout=[dtypes.float32],
            f=_remote_fn,
            target="/cpu:1")[0]

    async_executor = executor.new_executor(enable_async=True)
    cancel_mgr = cancellation.CancellationManager()
    with context.executor_scope(async_executor):
      # This should never finish.
      cancel_mgr.get_cancelable_function(run.get_concrete_function())()
    with ops.device("/cpu:0"):
      collective_ops.all_reduce_v2([1.],
                                   group_size=2,
                                   group_key=1,
                                   instance_key=1)
    cancel_mgr.start_cancel()
    with self.assertRaises(errors.CancelledError):
      async_executor.wait()

  @test_util.run_deprecated_v1
  def testIf(self):

    @function.Defun(dtypes.float32)
    def Twice(x):
      return x * 2

    @function.Defun(dtypes.float32)
    def Thrice(x):
      return x * 3 + 1

    with self.test_session(use_gpu=False) as sess:

      x = array_ops.placeholder(dtypes.float32)
      ret = functional_ops.If(math_ops.greater(x, 0), [x], Twice, Thrice)[0]

      self.assertAllEqual(sess.run(ret, feed_dict={x: 9.}), 18.)
      self.assertAllEqual(sess.run(ret, feed_dict={x: -8.}), -23.)
      self.assertAllEqual(sess.run(ret, feed_dict={x: 0.}), 1.)

  def testWhile(self):

    for use_gpu in (True, False):
      with ops.Graph().as_default() as g:

        @function.Defun(*[dtypes.float32] * 2)
        def Cond(n, unused_x):
          return n > 0

        @function.Defun(*[dtypes.float32] * 2)
        def Body(n, x):
          return n - 1, x + n

        def Run(sess, n):
          return sess.run(functional_ops.While([n, 0.], Cond, Body))[1]

        with self.session(graph=g, use_gpu=use_gpu) as sess:
          self.assertAllEqual(Run(sess, 20.), 210.)
          self.assertAllEqual(Run(sess, 100.), 5050.)

  def testToBool(self):
    # For 0D tensors, the truthiness depends on whether the value is "zero".
    self.assertAllEqual(gen_functional_ops.to_bool(0), False)
    self.assertAllEqual(gen_functional_ops.to_bool(1), True)
    self.assertAllEqual(gen_functional_ops.to_bool(42), True)
    self.assertAllEqual(gen_functional_ops.to_bool(0.), False)
    self.assertAllEqual(gen_functional_ops.to_bool(1.), True)
    self.assertAllEqual(gen_functional_ops.to_bool(42.), True)
    self.assertAllEqual(gen_functional_ops.to_bool(False), False)
    self.assertAllEqual(gen_functional_ops.to_bool(True), True)
    # For strings, "zero" is the empty string.
    self.assertAllEqual(gen_functional_ops.to_bool(""), False)
    self.assertAllEqual(gen_functional_ops.to_bool("a"), True)

    # For >0D tensors, the truthiness only depends on whether there are
    # elements or not.
    self.assertAllEqual(gen_functional_ops.to_bool([]), False)
    self.assertAllEqual(gen_functional_ops.to_bool([[]]), False)
    self.assertAllEqual(gen_functional_ops.to_bool([[[]]]), False)
    self.assertAllEqual(gen_functional_ops.to_bool([0]), True)
    self.assertAllEqual(gen_functional_ops.to_bool([1]), True)
    self.assertAllEqual(gen_functional_ops.to_bool([[0]]), True)
    self.assertAllEqual(gen_functional_ops.to_bool([False]), True)
    self.assertAllEqual(gen_functional_ops.to_bool([True]), True)

  # Like above, but using int32 in order to ensure that int32 tensors don't get
  # copied to the GPU during the application of the while.
  def testWhileInt32(self):
    with ops.Graph().as_default() as g:

      @function.Defun(*[dtypes.int32] * 2)
      def Cond(n, unused_x):
        return n > 0

      @function.Defun(*[dtypes.int32] * 2)
      def Body(n, x):
        return n - 1, x + n

      def Run(sess, n):
        return sess.run(functional_ops.While([n, 0], Cond, Body))[1]

      with self.session(graph=g, use_gpu=True) as sess:
        self.assertAllEqual(Run(sess, 20), 210)
        self.assertAllEqual(Run(sess, 100), 5050)

  @test_util.run_deprecated_v1
  def testWhileLowering(self):

    def Run(n, fetch_by_name):
      for use_gpu in (True, False):
        with ops.Graph().as_default() as g:

          @function.Defun(*[dtypes.float32] * 2)
          def Cond(n, unused_x):
            return n > 0

          @function.Defun(*[dtypes.float32] * 2)
          def Body(n, x):
            return n - 1, x + n

          # outputs: [0, n*(n+1)/2]
          outputs = functional_ops.While([n, 0.], Cond, Body, name="my_while")

          # `outputs` is the list of output tensors of the While op. We
          # arbitrarily choose the 0th tensor to get the While op and set the
          # lowering attribute on it.
          outputs[0].op._set_attr("_lower_using_switch_merge",
                                  attr_value_pb2.AttrValue(b=True))
          if not fetch_by_name:
            fetch = outputs[1]
          else:
            fetch = "my_while:1"
        with self.session(graph=g, use_gpu=use_gpu) as sess:
          return self.evaluate(fetch)

    self.assertAllEqual(Run(20., False), 210.)
    self.assertAllEqual(Run(20., True), 210.)
    self.assertAllEqual(Run(100., False), 5050.)
    self.assertAllEqual(Run(100., True), 5050.)

  @test_util.run_v1_only("b/120545219")
  @test_util.disable_xla("b/123337890")  # Different error message
  def testWhileError(self):
    for use_gpu in (True, False):
      with ops.Graph().as_default() as g:

        @function.Defun(*[dtypes.float32] * 2)
        def Cond(n, unused_x):
          return n > 0

        @function.Defun(*[dtypes.float32] * 2)
        def CondReturnsTooManyArgs(n, x):
          return n > 0, x

        @function.Defun(*[dtypes.float32] * 2)
        def Body(n, x):
          return n - 1, x + n

        @function.Defun(*[dtypes.float32] * 2)
        def BodyReturnsTooManyArgs(n, x):
          return n - 1, x + n, x

        with self.session(graph=g, use_gpu=use_gpu):
          with self.assertRaisesRegex(
              errors.InvalidArgumentError,
              "Expected a single scalar.*got 2 tensors."):
            functional_ops.While([5., 0.], CondReturnsTooManyArgs,
                                 Body)[0].eval()
          with self.assertRaisesRegex(
              errors.InvalidArgumentError,
              "While loop body returned 3 arguments. Expected: 2"):
            functional_ops.While([5., 0.], Cond,
                                 BodyReturnsTooManyArgs)[0].eval()

  def testWhileInMultipleSubgraphs(self):

    for use_gpu in (True, False):
      with ops.Graph().as_default() as g:

        @function.Defun(*[dtypes.float32] * 2)
        def Cond(n, x):  # pylint: disable=unused-argument
          return n > 0

        @function.Defun(*[dtypes.float32] * 2)
        def Body(n, x):
          return n - 1, x + n

        with self.session(graph=g, use_gpu=use_gpu) as sess:
          n = array_ops.placeholder(dtypes.float32)
          _, result = functional_ops.While([n, 0.], Cond, Body)
          c = constant_op.constant(37.)

          self.assertAllEqual(210., sess.run(result, feed_dict={n: 20.}))
          self.assertAllEqual(5050., sess.run(result, feed_dict={n: 100.}))
          # Test that the result is the same when we run a different subgraph.
          self.assertAllEqual(5050.,
                              sess.run([result, c], feed_dict={n: 100.})[0])

  # pylint: disable=cell-var-from-loop
  def testWhileCapturedInputs(self):
    for use_gpu in (True, False):
      with ops.Graph().as_default() as g:
        v = variables.Variable(1.0)

        def TestCond(n, *args):
          del args
          return n < 10

        @function.Defun(*[dtypes.float32] * 2)
        def TestUnary(n, x):
          return math_ops.add(n, 1), x + n + v

        @function.Defun(*[dtypes.float32] * 3)
        def TestBinary(n, x, x2):
          return math_ops.add(n, 1), x + n + v, x2 + v

        with self.session(graph=g, use_gpu=use_gpu) as sess:
          result_unary = functional_ops.While(
              [1.0, 0.],
              function.Defun(*[dtypes.float32] * 2)(TestCond), TestUnary)
          result_binary = functional_ops.While(
              [1.0, 0., 0.],
              function.Defun(*[dtypes.float32] * 3)(TestCond), TestBinary)
          self.evaluate(variables.global_variables_initializer())
          assert len(result_unary) == 2
          self.assertEqual([10.0, 54.0], self.evaluate(result_unary))
          assert len(result_binary) == 3
          self.assertEqual([10.0, 54.0, 9.0], self.evaluate(result_binary))

          def TestCondCapture(n, *args):
            del args
            return math_ops.cast(n, dtypes.float32) + v < 10

          with self.assertRaises(ValueError):
            _ = functional_ops.While(
                [1],
                function.Defun(dtypes.int32)(TestCondCapture),
                function.Defun(dtypes.int32, dtypes.float32)(TestUnary))

  # pylint: enable=cell-var-from-loop

  def _tfSum(self, use_gpu, rewrite_with_while):
    with ops.Graph().as_default() as g:
      with self.session(graph=g, use_gpu=use_gpu) as sess:

        @function.Defun(dtypes.int32, dtypes.float32)
        def Body(n, x):
          return x + math_ops.cast(n, dtypes.float32)

        xs = [
            # 1 + 2  + ... + 20
            functional_ops.For(
                1, 21, 1, [0.], Body, rewrite_with_while=rewrite_with_while)[0],
            # 100 + 99 + ... + 1
            functional_ops.For(
                100, 0, -1, [0.], Body, rewrite_with_while=rewrite_with_while)
            [0],
        ]
        xvals = self.evaluate(xs)
      self.assertAllEqual(210, xvals[0])
      self.assertAllEqual(5050, xvals[1])

  def testFor(self):
    for use_gpu in (True, False):
      self._tfSum(use_gpu, False)

  def testForWithWhile(self):
    for use_gpu in (True, False):
      self._tfSum(use_gpu, True)

  def testForWithWhileNaming(self):
    g = ops.Graph()
    with g.as_default():

      @function.Defun(dtypes.int32, dtypes.float32, func_name="TestBody")
      def TestBody(n, x):
        return x + math_ops.cast(n, dtypes.float32)

      _ = functional_ops.For(
          1, 21, 1, [0.], TestBody, rewrite_with_while=True)[0]

    names = []
    for func in g.as_graph_def().library.function:
      names.append(func.signature.name)
    self.assertTrue("TestBody" in names)
    self.assertTrue("TestBody_Cond" in names)
    self.assertTrue("TestBody_Body" in names)

  @test_util.run_deprecated_v1
  def testForCapturedInputs(self):
    v = variables.Variable(1.0)

    @function.Defun(dtypes.int32)
    def TestNullary(n):
      v + math_ops.cast(n, dtypes.float32)  # pylint: disable=expression-not-assigned

    @function.Defun(dtypes.int32, dtypes.float32)
    def TestUnary(n, x):
      return x + math_ops.cast(n, dtypes.float32) + v

    @function.Defun(dtypes.int32, dtypes.float32, dtypes.float32)
    def TestBinary(n, x, x2):
      return x + math_ops.cast(n, dtypes.float32) + v, x2 + v

    for rewrite_with_while in (True, False):
      use_gpu = not rewrite_with_while
      with self.test_session(use_gpu=use_gpu) as sess:
        result_nullary = functional_ops.For(
            1, 10, 1, [], TestNullary,
            rewrite_with_while=rewrite_with_while)
        result_unary = functional_ops.For(
            1, 10, 1, [0.], TestUnary,
            rewrite_with_while=rewrite_with_while)
        result_binary = functional_ops.For(
            1, 10, 1, [0., 0.], TestBinary,
            rewrite_with_while=rewrite_with_while)
        self.evaluate(variables.global_variables_initializer())
        assert not result_nullary
        # The nullary variant doesn't return anything so we can't easily run it.
        # As a total hack, fetch the operation by name and run it.
        sess.run(ops.get_default_graph().get_operation_by_name(
            "While" if rewrite_with_while else "For"))
        assert len(result_unary) == 1
        self.assertEqual([54.0], self.evaluate(result_unary))
        assert len(result_binary) == 2
        self.assertEqual([54.0, 9.0], self.evaluate(result_binary))

  def _tfMLP(self, xval, wsval, bsval, rewrite_with_while):
    # On GPU, don't rewrite using a while loop.
    use_gpu = not rewrite_with_while
    with self.test_session(use_gpu=use_gpu):

      @function.Defun(dtypes.int32, *[dtypes.float64] * 3)
      def MLP(i, a, ws, bs):
        a = math_ops.tanh(math_ops.matmul(a, ws[i, :]) + bs[i, :])
        return a, ws, bs

      ret = functional_ops.For(
          0,
          wsval.shape[0],
          1, [xval, wsval, bsval],
          MLP,
          rewrite_with_while=rewrite_with_while)[0]

      return self.evaluate(ret)

  def _npMLP(self, xval, wsval, bsval):
    for i in range(wsval.shape[0]):
      xval = np.tanh(np.dot(xval, wsval[i, :]) + bsval[i, :])
    return xval

  def _testForMLP(self, rewrite_with_while):
    # We construct a 5-layer Multi-Layer Perceptron network here.
    # Each layer have the same number of hidden unites (3), and the
    # activation function is tanh().  We feed the input (xval) with
    # batch size 2.
    xval = np.random.normal(size=(2, 3))
    wsval = np.random.normal(size=(5, 3, 3))
    bsval = np.random.normal(size=(5, 3))
    np_ans = self._npMLP(xval, wsval, bsval)
    tf_for_ans = self._tfMLP(xval, wsval, bsval, rewrite_with_while)
    self.assertAllClose(np_ans, tf_for_ans)

  @test_util.run_deprecated_v1
  def testForMLP(self):
    self._testForMLP(False)

  @test_util.run_deprecated_v1
  @test_util.disable_xla(
      "Test uses strided slice without compile time constant values")
  def testForMLPWhile(self):
    self._testForMLP(True)

  @test_util.run_v1_only("b/120545219")
  def testForError(self):

    @function.Defun(dtypes.int32, dtypes.float32)
    def Foo(i, v):
      return math_ops.cast(i, dtypes.float32) + v

    @function.Defun(dtypes.int32, dtypes.float32)
    def ReturnsTooManyArgs(unused_i, v):
      return v, v

    with self.test_session():
      with self.assertRaisesRegex(errors.InvalidArgumentError,
                                  "must be a scalar"):
        functional_ops.For([0], 10, 1, [0.0], Foo)[0].eval()
      with self.assertRaisesRegex(errors.InvalidArgumentError,
                                  "Invalid start/limit/delta"):
        functional_ops.For(0, 10, -1, [0.0], Foo)[0].eval()
      with self.assertRaisesRegex(
          errors.InvalidArgumentError,
          "For loop body returned 2 arguments. Expected: 1"):
        functional_ops.For(0, 10, 1, [0.0], ReturnsTooManyArgs)[0].eval()

  @test_util.run_deprecated_v1
  def testGradient(self):

    @function.Defun(dtypes.float32)
    def Poly(x):
      # y = 2x^3+3x^2+4x+8
      return 2 * x * x * x + 3 * x * x + 4 * x + 8

    @function.Defun(dtypes.float32)
    def Grad(x):
      # dy/dx = dy/dy * dy/dx = 1.0 * (6x^2+6x+4)
      return functional_ops.Gradient([x, 1.0], Poly)[0]

    with self.test_session(use_gpu=False) as sess:
      a = constant_op.constant(0.)
      avals = [Poly(a), Grad(a)]
      b = constant_op.constant(1.)
      bvals = [Poly(b), Grad(b)]
      self.assertAllEqual(self.evaluate(avals), [8., 4.])
      self.assertAllEqual(self.evaluate(bvals), [17., 16.])

  @test_util.run_v2_only
  def testCollective(self):
    context._reset_context()
    logical_devices = []
    logical_devices.append(context.LogicalDeviceConfiguration())
    logical_devices.append(context.LogicalDeviceConfiguration())
    framework_config.set_logical_device_configuration(
        framework_config.list_physical_devices("CPU")[0], logical_devices)

    @function.Defun(dtypes.float32)
    def collective_fn(t):
      # Run a dummy collective of group size 1 to test the setup.
      return collective_ops.all_reduce_v2(
          t, group_size=1, group_key=1, instance_key=1)

    @eager_def_function.function
    def run():
      with ops.device("/cpu:0"):
        return functional_ops.remote_call(
            args=[constant_op.constant([1.])] + collective_fn.captured_inputs,
            Tout=[dtypes.float32],
            f=collective_fn,
            target="/cpu:1")

    self.assertAllEqual(run(), [[1.]])


@test_util.run_all_in_graph_and_eager_modes
@test_util.with_control_flow_v2
class FunctionalOpsCaseTest(test.TestCase):

  def testCase(self):
    @eager_def_function.function
    def two(x):
      return x * 2

    @eager_def_function.function
    def three(x):
      return x * 3

    @eager_def_function.function
    def four(x):
      return x * 4

    def f(branch, x):
      tmpl = array_ops.zeros_like(x)
      return array_ops.identity(gen_functional_ops.case(
          branch, input=[x], Tout=[dtypes.float32],
          branches=[f.get_concrete_function(tmpl)
                    for f in (two, three, four)])[0])
    one = array_ops.ones([])
    self.assertAllEqual(np.float32(2), self.evaluate(f(0, one)))
    self.assertAllEqual(np.float32(3), self.evaluate(f(1, one)))
    self.assertAllEqual(np.float32(4), self.evaluate(f(2, one)))
    self.assertAllEqual(np.float32(4), self.evaluate(f(-1, one)))  # <0 default
    self.assertAllEqual(np.float32(4), self.evaluate(f(6, one)))  # >=N default

  @test_util.run_deprecated_v1
  @test_util.disable_xla("Don't lower for XLA")
  def testSkipEagerCaseLoweringPreservesNameForFetch(self):
    for use_gpu in (True, False):
      def Run(branch, x, fetch_by_name, use_gpu=use_gpu):
        with ops.Graph().as_default() as g:
          @function.Defun(dtypes.float32)
          def two(x):
            return -1, x * 2

          @function.Defun(dtypes.float32)
          def three(x):
            return 0, x * 3

          @function.Defun(dtypes.float32)
          def four(x):
            return 1, x * 4

          outputs = gen_functional_ops.case(branch, input=[x],
                                            Tout=[dtypes.int32, dtypes.float32],
                                            branches=[two, three, four],
                                            name="my_case")

          # `outputs` is the list of output tensors of the Case op. We
          # arbitrarily choose the 0th tensor to get the Case op and set the
          # lowering attribute on it.
          outputs[0].op._set_attr("_lower_using_switch_merge",
                                  attr_value_pb2.AttrValue(b=True))
          outputs = array_ops.identity_n(outputs)
        with self.session(graph=g, use_gpu=use_gpu) as sess:
          return sess.run("my_case:1" if fetch_by_name else outputs[1])

      self.assertAllEqual(2 * 1., Run(0, 1., False))
      self.assertAllEqual(2 * 1., Run(0, 1., True))
      self.assertAllEqual(3 * 7., Run(1, 7., False))
      self.assertAllEqual(3 * 7., Run(1, 7., True))
      self.assertAllEqual(4 * -3., Run(2, -3., False))
      self.assertAllEqual(4 * -3., Run(2, -3., True))
      self.assertAllEqual(4 * -4., Run(7, -4., False))  # >= N default
      self.assertAllEqual(4 * -4., Run(7, -4., True))  # >= N default
      self.assertAllEqual(4 * -5., Run(-1, -5., False))  # <0 default
      self.assertAllEqual(4 * -5., Run(-1, -5., True))  # <0 default

  @test_util.disable_xla("Don't lower for XLA")
  def testCaseLowering(self):
    for use_gpu in (True, False):
      @eager_def_function.function
      def Run(branch, x):
        @function.Defun(dtypes.float32)
        def two(x):
          return -1, x * 2

        @function.Defun(dtypes.float32)
        def three(x):
          return 0, x * 3

        @function.Defun(dtypes.float32)
        def four(x):
          return 1, x * 4

        outputs = gen_functional_ops.case(branch, input=[x],
                                          Tout=[dtypes.int32, dtypes.float32],
                                          branches=[two, three, four])

        # `outputs` is the list of output tensors of the Case op. We
        # arbitrarily choose the 0th tensor to get the Case op and set the
        # lowering attribute on it.
        outputs[0].op._set_attr("_lower_using_switch_merge",
                                attr_value_pb2.AttrValue(b=True))
        outputs = array_ops.identity_n(outputs)
        return outputs[1]

      with ops.device(test.gpu_device_name() if use_gpu else "CPU:0"):
        self.assertAllEqual(2 * 1., self.evaluate(Run(0, 1.)))
        self.assertAllEqual(3 * 7., self.evaluate(Run(1, 7.)))
        self.assertAllEqual(4 * -3., self.evaluate(Run(2, -3.)))
        self.assertAllEqual(4 * -4., self.evaluate(Run(7, -4.)))  # >=N default
        self.assertAllEqual(4 * -5., self.evaluate(Run(-1, -5.)))  # <0 default

if __name__ == "__main__":
  test.main()

# pylint: enable=invalid-name
