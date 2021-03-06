# -*- coding: utf-8 -*-

import os

import pytest
from mock import Mock, patch, sentinel

from botocore.exceptions import ClientError

from sceptre.exceptions import RetryLimitExceededError
from sceptre.exceptions import ProtectedStackError
from sceptre.helpers import exponential_backoff
from sceptre.helpers import get_subclasses
from sceptre.helpers import camel_to_snake_case
from sceptre.helpers import execution_protection
from sceptre.helpers import recurse_into_sub_environments
from sceptre.helpers import get_name_tuple
from sceptre.helpers import resolve_stack_name
from sceptre.helpers import get_external_stack_name
from sceptre.hooks import Hook
from sceptre.resolvers import Resolver
from sceptre.stack import Stack


class TestHelpers(object):

    def test_exponential_backoff_returns_response_correctly(self):
        def func(*args, **kwargs):
            return sentinel.response

        response = exponential_backoff(func)()

        assert response == sentinel.response

    @patch("sceptre.helpers.time")
    def test_exponential_backoff_pauses_when_request_limit_hit(
            self, mock_time
    ):
        mock_func = Mock()
        mock_func.side_effect = [
            ClientError(
                {
                    "Error": {
                        "Code": "Throttling",
                        "Message": "Request limit hit"
                    }
                },
                sentinel.operation
            ),
            sentinel.response
        ]
        # The attribute function.__name__ is required by the decorator @wraps.
        mock_func.__name__ = "mock_func"

        exponential_backoff(mock_func)()
        mock_time.sleep.assert_called_once_with(1)

    def test_exponential_backoff_raises_exception(self):
        mock_func = Mock()
        mock_func.side_effect = ClientError(
            {
                "Error": {
                    "Code": 500,
                    "Message": "Boom!"
                }
            },
            sentinel.operation
        )
        # The attribute function.__name__ is required by the decorator @wraps.
        mock_func.__name__ = "mock_func"

        with pytest.raises(ClientError) as e:
            exponential_backoff(mock_func)()
        assert e.value.response["Error"]["Code"] == 500
        assert e.value.response["Error"]["Message"] == "Boom!"

    @patch("sceptre.helpers.time")
    def test_exponential_backoff_raises_retry_limit_exceeded_exception(
            self, mock_time
    ):
        throttling_error = ClientError(
            {
                "Error": {
                    "Code": "Throttling",
                    "Message": "Request limit hit"
                }
            },
            sentinel.operation
        )
        mock_func = Mock()

        # RetryLimitExceededException should be raised after five throttling
        # errors.
        mock_func.side_effect = [throttling_error for _ in range(5)]

        # The attribute function.__name__ is required by the decorator @wraps.
        mock_func.__name__ = "mock_func"

        with pytest.raises(RetryLimitExceededError):
            exponential_backoff(mock_func)()

    def test_get_subclasses(self):
        directory = os.path.join(os.getcwd(), "sceptre", "resolvers")
        classes = get_subclasses(Resolver, directory)

        # This is actually checking a property of the classes, which isn't
        # ideal but it's difficult to assert that the classes themselves are
        # the same.
        assert classes["environment_variable"].__name__ == \
            "EnvironmentVariable"
        assert classes["file_contents"].__name__ == \
            "FileContents"
        assert classes["stack_output_external"].__name__ == \
            "StackOutputExternal"
        assert classes["stack_output"].__name__ ==  \
            "StackOutput"
        assert classes["project_variables"].__name__ == \
            "ProjectVariables"
        assert len(classes) == 5

    def test_execution_protection_allows_function_execution(self):
        mock_stack = Mock(spec=Stack)
        mock_stack.config = {"protect": False}
        mock_function = Mock()
        mock_stack.mock_function = mock_function
        mock_stack.mock_function.__name__ = 'mock_function'

        execution_protection(mock_stack.mock_function)(mock_stack)

        assert mock_stack.mock_function.call_count == 1

    def test_execution_protection_raises_exception(self):
        mock_stack = Mock(spec=Stack)
        mock_stack.config = {"protect": True}
        mock_function = Mock()
        mock_stack.full_stack_name = sentinel.name
        mock_stack.mock_function = mock_function
        mock_stack.mock_function.__name__ = 'mock_function'

        with pytest.raises(ProtectedStackError):
            execution_protection(mock_stack.mock_function)(mock_stack)

    def test_camel_to_snake_case(self):
        snake_case_string = camel_to_snake_case("Bash")
        assert snake_case_string == "bash"
        snake_case_string = camel_to_snake_case("ASGScheduledActions")
        assert snake_case_string == "asg_scheduled_actions"

    def test_recurse_into_sub_environments_with_leaf_object(self):
        class MockEnv(object):

            def __init__(self, name, is_leaf):
                self.name = name
                self.is_leaf = is_leaf

            @recurse_into_sub_environments
            def do(self):
                return {self.name: sentinel.response}

        mock_env = MockEnv("mock_stack", True)
        response = mock_env.do()
        assert response == {"mock_stack": sentinel.response}

    def test_recurse_into_sub_environments_with_non_leaf_object(self):
        class MockEnv(object):

            def __init__(self, name, is_leaf):
                self.name = name
                self.is_leaf = is_leaf

            @recurse_into_sub_environments
            def do(self):
                return {self.name: sentinel.response}

        mock_env = MockEnv("non-leaf-stack", False)

        # Add leaf sub-environments
        mock_env.environments = {
            "mock-env-1": MockEnv("leaf-stack-1", True),
            "mock-env-2": MockEnv("leaf-stack-2", True)
        }

        response = mock_env.do()
        assert response == {
            "leaf-stack-1": sentinel.response,
            "leaf-stack-2": sentinel.response
        }

    def test_get_name_tuple(self):
        result = get_name_tuple("dev/ew1/jump-host")
        assert result == ("dev", "ew1", "jump-host")

    def test_resolve_stack_name(self):
        result = resolve_stack_name("dev/ew1/subnet", "vpc")
        assert result == "dev/ew1/vpc"
        result = resolve_stack_name("dev/ew1/subnet", "prod/ue1/vpc")
        assert result == "prod/ue1/vpc"

    def test_get_external_stack_name(self):
        result = get_external_stack_name("prj", "dev/ew1/jump-host")
        assert result == "prj-dev-ew1-jump-host"

    def test_get_subclasses_with_invalid_directory(self):
        with pytest.raises(TypeError):
            get_subclasses(Hook, 1)
