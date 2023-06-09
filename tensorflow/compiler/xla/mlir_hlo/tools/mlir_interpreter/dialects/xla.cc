/* Copyright 2023 The TensorFlow Authors. All Rights Reserved.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
==============================================================================*/

#include "tools/mlir_interpreter/framework/registration.h"

namespace mlir {
namespace interpreter {
namespace {

llvm::SmallVector<InterpreterValue> bufferToMem(
    MutableArrayRef<InterpreterValue> args, mlir::Operation*,
    InterpreterState&) {
  return {args[0]};
}

REGISTER_MLIR_INTERPRETER_OP("xla_cpu.memref_element_cast",
                             "builtin.unrealized_conversion_cast");
REGISTER_MLIR_INTERPRETER_OP("xla_framework.buffer_to_mem", bufferToMem);

}  // namespace
}  // namespace interpreter
}  // namespace mlir
