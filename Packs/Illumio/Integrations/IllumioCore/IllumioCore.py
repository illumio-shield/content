import demistomock as demisto
import urllib3
from CommonServerPython import *  # noqa # pylint: disable=unused-wildcard-import
from CommonServerUserPython import *  # noqa
from illumio import PolicyComputeEngine, convert_protocol, ServicePort
from illumio.explorer import TrafficQuery

urllib3.disable_warnings()

''' CONSTANTS '''

MIN_PORT = 1
MAX_PORT = 65535
HR_DATE_FORMAT = "%d %b %Y, %I:%M %p"
VALID_PROTOCOLS = ['tcp', 'udp']
VALID_POLICY_DECISIONS = ['potentially_blocked', 'blocked', 'unknown', 'allowed']

'''EXCEPTION CLASS'''


class InvalidPortException(Exception):
    """Exception class for Invalid port."""

    def __init__(self, port):
        self.message = "{} is an invalid value for port. Value must be in 1 to 65535.".format(port)
        super().__init__(self.message)


class InvalidSingleSelectException(Exception):
    """Exception class for invalid protocol."""

    def __init__(self, value, argument, argument_list):
        self.message = "{} is an invalid value for {}. Possible values are: {}.".format(value, argument, argument_list)
        super().__init__(self.message)


class InvalidMultiSelectException(Exception):
    """Exception class for invalid protocol."""

    def __init__(self, argument, argument_list):
        self.message = "Invalid value for {}. Possible comma separated values are {}.".format(argument, argument_list)
        super().__init__(self.message)


''' HELPER FUNCTIONS '''


def validate_arguments_for_traffic_analysis(port: Optional[int], policy_decisions: list, protocol: str):
    """Validate arguments for illumio-traffic-analysis command.

    Args:
        port: Port number.
        policy_decisions: Policy decision to include in the search result.
        protocol: Communication protocol.

    Returns:
        str: Error if value of the argument is not valid.
    """
    if port < MIN_PORT or port > MAX_PORT:  # type: ignore
        raise InvalidPortException(port)

    for decision in policy_decisions:
        if decision not in VALID_POLICY_DECISIONS:
            raise InvalidMultiSelectException('policy_decisions', VALID_POLICY_DECISIONS)

    if protocol not in VALID_PROTOCOLS:
        raise InvalidSingleSelectException(protocol, "protocol", VALID_PROTOCOLS)


def prepare_hr_for_traffic_analysis(response: list, protocol: str) -> str:
    """Prepare Human Readable output for traffic analysis command.

    Args:
        response: Response from the SDK.
        protocol: Communication protocol.

    Returns:
        markdown string to be displayed in the war room.
    """
    hr_output = []
    for traffic in response:
        hr_output.append({
            "Source IP": traffic.get('src', {}).get('ip'),
            "Destination IP": traffic.get('dst', {}).get('ip'),
            "Destination Workload Hostname": traffic.get('dst', {}).get('workload', {}).get('hostname'),
            "Service Port": traffic.get('service', {}).get('port'),
            "Service Protocol": protocol,
            "Policy Decision": traffic.get('policy_decision'),
            "State": traffic.get("state"),
            "Flow Direction": traffic.get('flow_direction'),
            "First Detected": arg_to_datetime(traffic.get('timestamp_range', {}).get('first_detected', '')).strftime(  # type: ignore # noqa
                HR_DATE_FORMAT),  # type: ignore # noqa
            "Last Detected": arg_to_datetime(traffic.get('timestamp_range', {}).get('last_detected', '')).strftime(  # type: ignore # noqa
                HR_DATE_FORMAT)
        })

    headers = ["Source IP", "Destination IP", "Destination Workload Hostname", "Service Port", "Service Protocol",
               "Policy Decision", "State", "Flow Direction", "First Detected", "Last Detected"]

    return tableToMarkdown("Traffic Analysis:", hr_output, headers=headers, removeNull=True)


def validate_required_parameters(**kwargs) -> None:
    """Raise an error for a required parameter.

    Enter your required parameters as keyword arguments to check
    whether they hold a value or not.

    Args:
        **kwargs: keyword arguments to check the required values for.

    Returns:
        Error if the value of the parameter is "", [], (), {}, None.
    """
    for key, value in kwargs.items():
        if not value:
            raise ValueError("{} is a required parameter. Please provide correct value.".format(key))


def trim_spaces_from_args(args: Dict) -> Dict:
    """Trim spaces from values of the args dict.

    Args:
        args: Dict to trim spaces from.

    Returns: Arguments after trim spaces.
    """
    for key, val in args.items():
        if isinstance(val, str):
            args[key] = val.strip()

    return args


''' COMMAND FUNCTIONS '''


def test_module(client: PolicyComputeEngine) -> str:
    """Tests API connectivity and authentication.

    Returning 'ok' indicates that the integration works like it is supposed to.
    Connection to the service is successful.

    Args:
        client: PolicyComputeEngine to be used.

    Returns: 'ok' if test passed, anything else will fail the test.
    """
    response = client.check_connection()
    if response:
        return 'ok'
    raise ValueError("Failed to establish connection with provided credentials.")


def illumio_traffic_analysis_command(client: PolicyComputeEngine, args: Dict[str, Any]) -> CommandResults:
    """Retrieve the traffic for a particular port and protocol.

    Args:
        client: PolicyComputeEngine to use.
        args: arguments obtained from demisto.args()

    Returns: CommandResult object
    """
    port = arg_to_number(args.get('port'))
    protocol = args.get('protocol', '').lower()
    start_time = arg_to_datetime(args.get('start_time')).isoformat()  # type: ignore
    end_time = arg_to_datetime(args.get('end_time')).isoformat()  # type: ignore
    policy_decisions = argToList(args.get('policy_decisions'))
    validate_required_parameters(port=port, protocol=protocol, start_time=start_time, end_time=end_time,
                                 policy_decisions=policy_decisions)
    validate_arguments_for_traffic_analysis(port, policy_decisions, protocol)  # type: ignore
    query_name = 'Traffic analysis'
    proto = convert_protocol(protocol)
    service = ServicePort(port, proto=proto)

    traffic_query = TrafficQuery.build(start_date=start_time, end_date=end_time, policy_decisions=policy_decisions,
                                       include_services=[service])

    response = client.get_traffic_flows_async(query_name=query_name, traffic_query=traffic_query)
    json_response = []
    for resp in response:
        resp = resp.to_json()
        json_response.append(resp)

    readable_output = prepare_hr_for_traffic_analysis(json_response, protocol)
    outputs_response = remove_empty_elements(json_response)  # type: ignore
    return CommandResults(
        outputs_prefix="Illumio.TrafficFlows",
        outputs_key_field="href",
        outputs=outputs_response,
        readable_output=readable_output,
        raw_response=json_response
    )


def main():
    """Parse params and runs command functions."""
    try:
        command = demisto.command()
        demisto.debug(f"Command being called is {command}.")

        params = demisto.params()
        api_user = params.get('api_user')
        api_key = params.get('api_key')

        port = arg_to_number(params.get('port'))
        if port < MIN_PORT or port > MAX_PORT:  # type: ignore
            raise InvalidPortException(port)

        org_id = arg_to_number(params.get('org_id'), required=True)
        if org_id <= 0:  # type: ignore
            raise ValueError(
                "{} is an invalid value. Organization ID must be a non-zero and positive numeric value.".format(org_id))

        base_url = params.get('url')
        proxy = handle_proxy()

        client = PolicyComputeEngine(url=base_url, port=port, org_id=org_id)
        client.set_proxies(http_proxy=proxy.get("http", None), https_proxy=proxy.get('https', None))
        client.set_credentials(api_user, api_key)

        if command == 'test-module':
            return_results(test_module(client))
        else:
            ILLUMIO_COMMANDS = {
                'illumio-traffic-analysis': illumio_traffic_analysis_command}
            if ILLUMIO_COMMANDS.get(command):
                args = demisto.args()
                remove_nulls_from_dictionary(trim_spaces_from_args(args))
                return_results(ILLUMIO_COMMANDS[command](client, args))
            else:
                raise NotImplementedError(f'Command {command} is not implemented')
    except Exception as e:
        demisto.error(traceback.format_exc())
        return_error(f'Failed to execute {command} command.\nError:\n{str(e)}')


if __name__ in ('__main__', '__builtin__', 'builtins'):  # pragma: no cover
    main()
