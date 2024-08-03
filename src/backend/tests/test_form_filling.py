import os
from tempfile import mkdtemp
from zipfile import ZipFile
from typing import Dict, List, Callable, Any
from pathlib import Path
import pickle
from datetime import datetime

import pytest
from unittest.mock import patch, Mock, MagicMock

from expungeservice.expunger import Expunger
from expungeservice.form_filling import FormFilling, PDF, UserInfo, CaseResults
from expungeservice.record_merger import RecordMerger
from expungeservice.record_summarizer import RecordSummarizer
from expungeservice.models.case import Case
from expungeservice.models.charge import Charge
from expungeservice.models.charge_types.contempt_of_court import ContemptOfCourt
from expungeservice.models.charge_types.felony_class_b import FelonyClassB
from expungeservice.models.charge_types.felony_class_c import FelonyClassC
from expungeservice.models.charge_types.marijuana_eligible import MarijuanaViolation
from expungeservice.models.charge_types.misdemeanor_class_a import MisdemeanorClassA
from expungeservice.models.charge_types.misdemeanor_class_bc import MisdemeanorClassBC
from expungeservice.models.charge_types.reduced_to_violation import ReducedToViolation
from expungeservice.models.charge_types.violation import Violation
from expungeservice.models.expungement_result import ChargeEligibilityStatus
from expungeservice.models.disposition import DispositionStatus
from expungeservice.util import DateWithFuture

from tests.factories.crawler_factory import CrawlerFactory
from tests.fixtures.case_details import CaseDetails
from tests.fixtures.john_doe import JohnDoe
from tests.fixtures.form_filling_data import (
    oregon_john_common_pdf_fields,
    multnomah_arrest_john_common_pdf_fields,
    multnomah_conviction_john_common_pdf_fields,
    oregon_arrest_john_common_pdf_fields,
    oregon_conviction_john_common_pdf_fields,
)


def create_date(y, m, d):
    return DateWithFuture.fromdatetime(datetime(y, m, d))


def assert_pdf_values(pdf: PDF, expected: Dict[str, str]):
    annotation_dict = pdf.get_annotation_dict()

    for key, value in expected.items():
        assert annotation_dict[key].V == value, key

    # Ensure other fields are not set.
    for key in set(annotation_dict) - set(expected):
        value = annotation_dict[key].V
        if annotation_dict[key].FT == PDF.TEXT_TYPE:
            assert value in [None, "<>"], key
        if annotation_dict[key].FT == PDF.BUTTON_TYPE:
            assert value != PDF.BUTTON_ON, key


def test_normal_conviction_uses_multnomah_conviction_form():
    record = CrawlerFactory.create(JohnDoe.SINGLE_CASE_RECORD, {"CASEJD1": CaseDetails.CASEJD74})
    expunger_result = Expunger.run(record)
    merged_record = RecordMerger.merge([record], [expunger_result], [])
    record_summary = RecordSummarizer.summarize(merged_record, {})
    user_information = {
        "full_name": "",
        "date_of_birth": "",
        "phone_number": "",
        "mailing_address": "",
        "city": "",
        "state": "",
        "zip_code": "",
    }
    zip_path, zip_name = FormFilling.build_zip(record_summary, user_information)
    temp_dir = mkdtemp()
    with ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(temp_dir)
        for _root, _dir, files in os.walk(temp_dir):
            assert len(files) == 1


#########################################


class TestJohnCommonBuildZip:
    filename = "oregon.pdf"
    BASE_DIR = os.path.join(Path(__file__).parent.parent, "expungeservice", "files")
    expected_form_values = oregon_john_common_pdf_fields

    @patch("expungeservice.form_filling.FormFilling._get_pdf_file_name")
    @patch("expungeservice.form_filling.PdfWriter")
    @patch("expungeservice.form_filling.ZipFile")
    @patch("expungeservice.form_filling.mkdtemp")
    def test_form_fields_are_filled(self, mock_mkdtemp, MockZipFile, MockPdfWriter, mock_get_pdf_file_name):
        mock_mkdtemp.return_value = "foo"
        mock_get_pdf_file_name.side_effect = [
            self.filename,
            self.filename,
            self.filename,
            FormFilling.OSP_PDF_NAME + ".pdf",
        ]

        user_information = {
            "full_name": "John FullName Common",
            "date_of_birth": "11/22/1999",
            "mailing_address": "12345 NE Test Suite Drive #123",
            "phone_number": "555-555-1234",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97222",
        }
        # The pickle file was generated by setting the system date to 3/2/23 and using:
        # alias = {"first_name": "john", "middle_name": "", "last_name": "common", "birth_date": ""}
        # record_summary = Demo._build_record_summary([alias], {}, {}, Search._build_today("1/2/2023"))
        pickle_file = os.path.join(Path(__file__).parent, "fixtures", "john_common_record_summary.pickle")
        with open(pickle_file, "rb") as file:
            record_summary = pickle.load(file)

        FormFilling.build_zip(record_summary, user_information)

        # Check PDF form fields are correct.
        addpages_call_args_list = MockPdfWriter.return_value.addpages.call_args_list
        for i, args_list in enumerate(addpages_call_args_list):
            document_id = "document_" + str(i)
            args, _ = args_list
            pages = args[0]
            for idx, page in enumerate(pages):
                for annotation in page.Annots or []:
                    assert self.expected_form_values[document_id][idx][annotation.T] == annotation.V, annotation.T

        # Check PDF writer write paths.
        pdf_write_call_args_list = MockPdfWriter.return_value.write.call_args_list
        file_paths = [pdf_write_call_args_list[i][0][0] for i, _ in enumerate(pdf_write_call_args_list)]
        expected_file_paths = [
            "foo/COMMON NAME_200000_benton.pdf",
            "foo/COMMON NAME_110000_baker.pdf",
            "foo/COMMON A NAME_120000_baker.pdf",
            "foo/OSP_Form.pdf",
        ]
        assert set(file_paths) == set(expected_file_paths)

        # Check zip write paths.
        zip_write_call_args_list = MockZipFile.return_value.write.call_args_list
        zip_write_args = [zip_write_call_args_list[i][0] for i, _ in enumerate(zip_write_call_args_list)]
        expected_zip_write_args = [
            ("foo/COMMON NAME_200000_benton.pdf", "COMMON NAME_200000_benton.pdf"),
            ("foo/COMMON NAME_110000_baker.pdf", "COMMON NAME_110000_baker.pdf"),
            ("foo/COMMON A NAME_120000_baker.pdf", "COMMON A NAME_120000_baker.pdf"),
            ("foo/OSP_Form.pdf", "OSP_Form.pdf"),
        ]
        assert set(zip_write_args) == set(expected_zip_write_args)


BuildZipResult = Dict[str, Any]


class TestJohnCommonArrestBuildZip(TestJohnCommonBuildZip):
    filename = "oregon_arrest.pdf"
    expected_form_values: BuildZipResult = oregon_arrest_john_common_pdf_fields


class TestJohnCommonConvictionBuildZip(TestJohnCommonBuildZip):
    filename = "oregon_conviction.pdf"
    expected_form_values: BuildZipResult = oregon_conviction_john_common_pdf_fields


class TestJohnCommonMultnomahArrestBuildZip(TestJohnCommonBuildZip):
    filename = "multnomah_arrest.pdf"
    expected_form_values: BuildZipResult = multnomah_arrest_john_common_pdf_fields


class TestJohnCommonMultnomahConvictionBuildZip(TestJohnCommonBuildZip):
    filename = "multnomah_conviction.pdf"
    expected_form_values: BuildZipResult = multnomah_conviction_john_common_pdf_fields


#########################################


class TestPDFFileNameAndDownloadPath:
    def mock_case_results(self, county, has_convictions):
        mock_case_results = Mock(spec=CaseResults)
        #mock_case_results.county = county
        mock_case_results.case_name = "case_name"
        mock_case_results.case_number = "case_number"
        mock_case_results.has_conviction = has_convictions
        return mock_case_results

    def assert_correct_pdf_file_name(self, county: str, expected_file_name: str, has_convictions: bool = True):
        res = self.mock_case_results(county, has_convictions)
        file_name = FormFilling._get_pdf_file_name(res)

        assert file_name == expected_file_name

    def assert_correct_download_file_path(self, county: str, expected_file_name: str, has_convictions: bool):
        res = self.mock_case_results(county, has_convictions)
        file_path, file_name = FormFilling._build_download_file_path("dir", res)

        assert file_name == "case_name_case_number_" + expected_file_name
        assert file_path == "dir/case_name_case_number_" + expected_file_name

    def test_correct_pdf_path_is_built(self):
        self.assert_correct_pdf_file_name("Umatilla", "oregon_arrest.pdf", has_convictions=False)
        self.assert_correct_pdf_file_name("Umatilla", "oregon_conviction.pdf", has_convictions=True)

        self.assert_correct_pdf_file_name("Multnomah", "multnomah_arrest.pdf", has_convictions=False)
        self.assert_correct_pdf_file_name("Multnomah", "multnomah_conviction.pdf", has_convictions=True)

        self.assert_correct_pdf_file_name("unknown", "oregon.pdf", has_convictions=False)
        self.assert_correct_pdf_file_name("unknown", "oregon.pdf", has_convictions=True)

    def test_correct_download_file_path_is_built(self):
        self.assert_correct_download_file_path("Umatilla", "umatilla_with_arrest_order.pdf", has_convictions=False)
        self.assert_correct_download_file_path("Umatilla", "umatilla_with_conviction_order.pdf", has_convictions=True)

        self.assert_correct_download_file_path("Other", "other.pdf", has_convictions=False)
        self.assert_correct_download_file_path("Other", "other.pdf", has_convictions=True)

        # OSP_Form
        mock_user_info = Mock()  # not CaseResults
        file_path, file_name = FormFilling._build_download_file_path("dir", mock_user_info)

        assert file_name == "OSP_Form.pdf"
        assert file_path == "dir/OSP_Form.pdf"


class TestWarningsGeneration:
    lead_warning = (
        "# Warnings from RecordSponge  \n" + "Do not submit this page to the District Attorney's office.  \n \n"
    )
    partial_expungement_warning = "\\* This form will attempt to expunge a case in part. This is relatively rare, and thus these forms should be reviewed particularly carefully.  \n"

    def font_warning(self, field_name, value):
        return f'\\* * The font size of "{value[1:-1]}" was shrunk to fit the bounding box of "{field_name[1:-1]}". An addendum might be required if it still doesn\'t fit.  \n'

    @pytest.fixture
    def mapper_factory(self):
        def factory(has_ineligible_charges=False):
            mapper = MagicMock()
            setting = {"(has_ineligible_charges)": has_ineligible_charges}
            mapper.get.side_effect = setting.get
            return mapper

        return factory

    @pytest.fixture
    def shrunk_fields(self):
        shrunk_fields: Dict[str, str] = {}
        return shrunk_fields

    def test_no_warnings_generated_if_no_ineligible_charges_or_shrunk_fields(self, mapper_factory, shrunk_fields):
        warnings = FormFilling._generate_warnings_text(shrunk_fields, mapper_factory())
        assert warnings is None

    def test_warnings_generated_if_there_are_ineligible_charges(self, mapper_factory, shrunk_fields):
        expected = self.lead_warning
        expected += self.partial_expungement_warning

        mapper = mapper_factory(has_ineligible_charges=True)
        warnings = FormFilling._generate_warnings_text(shrunk_fields, mapper)
        assert warnings == expected

    def test_warnings_generated_if_there_are_shrunk_fields(self, mapper_factory, shrunk_fields):
        expected = self.lead_warning
        expected += self.font_warning("(foo)", "(foo value)")
        expected += self.font_warning("(bar)", "(bar value)")

        shrunk_fields = {"(foo)": "(foo value)", "(bar)": "(bar value)"}
        warnings = FormFilling._generate_warnings_text(shrunk_fields, mapper_factory())
        assert warnings == expected

    def test_warnings_generated_if_there_are_shrunk_fields_and_ineligible_charges(self, mapper_factory, shrunk_fields):
        expected = self.lead_warning
        expected += self.partial_expungement_warning
        expected += self.font_warning("(foo)", "(foo value)")

        mapper = mapper_factory(has_ineligible_charges=True)
        shrunk_fields = {"(foo)": "(foo value)"}
        warnings = FormFilling._generate_warnings_text(shrunk_fields, mapper)
        assert warnings == expected


#########################################


class TestBuildOSPPDF:
    def test_user_info_is_placed_in_osp_form(self):
        user_data = {
            "full_name": "foo bar",
            "date_of_birth": "1/2/1999",
            "mailing_address": "1234 NE Dev St. #12",
            "city": "Portland",
            "state": "OR",
            "zip_code": "97111",
            "phone_number": "555-555-1234",
        }
        expected_values = {
            "(Full Name)": "(foo bar)",
            "(Date of Birth)": "(1/2/1999)",
            "(Phone Number)": "(555-555-1234)",
            "(Mailing Address)": "(1234 NE Dev St. #12)",
            "(City)": "(Portland)",
            "(State)": "(OR)",
            "(Zip Code)": "(97111)",
        }
        user_info = UserInfo(
            counties_with_cases_to_expunge=[],
            has_eligible_convictions=False,
            **user_data,
        )
        pdf = FormFilling._create_pdf(user_info, validate_initial_pdf_state=True)
        assert_pdf_values(pdf, expected_values)


class PDFTestFixtures:
    county: str
    user_data = {
        "full_name": "foo bar",
        "date_of_birth": "1/2/1999",
        "mailing_address": "1234 NE Dev St. #12",
        "city": "Portland",
        "state": "OR",
        "zip_code": "97111",
        "phone_number": "555-555-1234",
    }

    @pytest.fixture
    def charge(self) -> Mock:
        charge = Mock(spec=Charge)
        charge.date = create_date(2020, 2, 3)
        charge.name = "a bad thing"
        charge.edit_status = "not delete"
        return charge

    @pytest.fixture
    def conviction_charge(self, charge: Mock) -> Mock:
        charge.expungement_result.charge_eligibility.status = ChargeEligibilityStatus.ELIGIBLE_NOW
        charge.charge_type = FelonyClassB()
        charge.disposition = Mock()
        charge.disposition.date = create_date(1999, 12, 3)
        charge.convicted.return_value = True
        charge.dismissed.return_value = False
        charge.probation_revoked = False
        return charge

    @pytest.fixture
    def dismissed_charge_factory(self) -> Callable:
        def factory(charge_year=2020, charge_month=2, charge_day=3) -> Mock:
            charge = Mock(spec=Charge)
            charge.name = "a bad thing"
            charge.edit_status = "not delete"
            charge.expungement_result.charge_eligibility.status = ChargeEligibilityStatus.ELIGIBLE_NOW
            charge.charge_type = Mock()
            charge.disposition = Mock()
            charge.disposition.date = create_date(2023, 6, 7)
            charge.date = create_date(charge_year, charge_month, charge_day)
            return charge

        return factory

    @pytest.fixture
    def case(self, charge) -> Mock:
        case = Mock(spec=Case)
        case.summary = Mock(autospec=True)
        case.summary.balance_due_in_cents = 0
        case.summary.location = self.county
        case.summary.name = "Case Name 0"
        case.summary.district_attorney_number = "DA num 0"
        case.summary.case_number = "base case number"
        case.charges = [charge]
        return case

    @pytest.fixture
    def pdf_factory(self, case: Mock):
        def factory(charges: List[Mock]) -> PDF:
            case.charges = charges
            case_results = CaseResults.build(case, self.user_data, sid="sid0")
            pdf = FormFilling._create_pdf(case_results, validate_initial_pdf_state=True)
            return pdf

        return factory


class TestBuildOregonPDF(PDFTestFixtures):
    county = "Washington"
    expected_county_data = {
        # county
        "(FOR THE COUNTY OF)": "(Washington)",
        # da_address
        "(the District Attorney at address 2)": "(District Attorney - 150 N First Avenue, Suite 300 - Hillsboro, OR 97124-3002)",
    }

    expected_base_values = {
        # constant
        "(Plaintiff)": "(State of Oregon)",
        # case_name
        "(Defendant)": "(Case Name 0)",
        # date_of_birth
        "(DOB)": "(1/2/1999)",
        # sid
        "(SID)": "(sid0)",
        # True
        "(I am not currently charged with a crime)": "/On",
        "(The arrest or citation I want to set aside is not for a charge of Driving Under the Influence of)": "/On",
        # arrest_dates
        "(Date of arrest)": "(Feb 3, 2020)",
        # True
        "(have sent)": "/On",
        # full_name
        "(Name typed or printed)": "(foo bar)",
        # mailing_address, city, state, zip_code, phone_number
        "(Address)": "(1234 NE Dev St. #12,    Portland,    OR,    97111,    555-555-1234)",
        # full_name
        "(Name typed or printed_2)": "(foo bar)",
    }
    expected_conviction_values = {
        # case_number_with_comments
        "(Case No)": "(base case number)",
        # not has_no_complaint
        "(record of arrest with charges filed and the associated check all that apply)": "/On",
        # conviction_dates
        "(Date of conviction contempt finding or judgment of GEI)": "(Dec 3, 1999)",
        # has_conviction
        "(conviction)": "/On",
        "(ORS 137225 does not prohibit a setaside of this conviction see Instructions)": "/On",
        "(I have fully completed complied with or performed all terms of the sentence of the court)": "/On",
    }
    expected_violation_values = {
        # has_violation_or_contempt_of_court
        "(Violation or Contempt of Court and)": "/On",
        "(1 year has passed since the later of the convictionfindingjudgment or release_2)": "/On",
        "(I have not been convicted of any other offense or found guilty except for insanity_2)": "/On",
    }

    def assert_pdf_values(self, pdf: PDF, new_expected_values):
        all_expected_values = {**self.expected_county_data, **self.expected_base_values, **new_expected_values}
        assert_pdf_values(pdf, all_expected_values)

    ############# tests #############

    def test_oregon_base_case(self, case: Mock):
        new_expected_values = {
            # case_number_with_comments
            "(Case No)": "(base case number \\(charge  only\\))",
            # not has_no_complaint
            "(record of arrest with charges filed and the associated check all that apply)": "/On",
        }
        case_results = CaseResults.build(case, self.user_data, sid="sid0")
        pdf = FormFilling._create_pdf(case_results)
        self.assert_pdf_values(pdf, new_expected_values)

    def test_has_no_complaint_has_dismissed(self, dismissed_charge_factory: Callable, pdf_factory: Callable):
        new_expected_values = {
            # has_no_complaint
            "(record of arrest with no charges filed)": "/On",
            "(no accusatory instrument was filed and at least 60 days have passed since the)": "/On",
            # has_dismissed
            "(an accusatory instrument was filed and I was acquitted or the case was dismissed)": "/On",
            "(record of citation or charge that was dismissedacquitted)": "/On",
            # case_number_with_comments
            "(Case No)": "(base case number)",
        }
        self.assert_pdf_values(pdf_factory([dismissed_charge_factory()]), new_expected_values)

    ##### conviction #####

    def test_has_probation_revoked(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(I was sentenced to probation in this case and)": "/On",
            "(My probation WAS revoked and 3 years have passed since the date of revocation)": "/On",
        }
        conviction_charge.charge_type = Mock()
        conviction_charge.probation_revoked = create_date(1988, 5, 3)

        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_class_b_felony(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Felony  Class B and)": "/On",
            "(7 years have passed since the later of the convictionjudgment or release date and)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity in)": "/On",
        }
        conviction_charge.charge_type = FelonyClassB()
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_class_c_felony(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Felony  Class C and)": "/On",
            "(5 years have passed since the later of the convictionjudgment or release date and)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity in_2)": "/On",
        }
        conviction_charge.charge_type = FelonyClassC()
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_class_a_misdeanor(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Misdemeanor  Class A and)": "/On",
            "(3 years have passed since the later of the convictionjudgment or release date and)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity in_3)": "/On",
        }
        conviction_charge.charge_type = MisdemeanorClassA()
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_class_bc_misdeanor(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Misdemeanor  Class B or C and)": "/On",
            "(1 year has passed since the later of the convictionfindingjudgment or release)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity)": "/On",
        }
        conviction_charge.charge_type = MisdemeanorClassBC()
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_violation(self, conviction_charge: Mock, pdf_factory: Callable):
        for charge_type in [Violation, ReducedToViolation, MarijuanaViolation]:
            conviction_charge.charge_type = charge_type()
            self.assert_pdf_values(
                pdf_factory([conviction_charge]), {**self.expected_conviction_values, **self.expected_violation_values}
            )

    def test_has_contempt_of_court_and_case_number_with_comments(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Case No)": "(base case number \\(charge second_part only\\))",
            "(contempt of court finding)": "/On",
        }
        conviction_charge.charge_type = ContemptOfCourt()
        conviction_charge.ambiguous_charge_id = "first_part-second_part"

        ineligible_charge = Mock(spec=Charge)
        ineligible_charge.date = create_date(2020, 2, 3)
        ineligible_charge.name = "an ineligible thing"
        ineligible_charge.edit_status = "not delete"

        all_expected_values = {
            **self.expected_conviction_values,
            **self.expected_violation_values,
            **new_expected_values,
        }
        self.assert_pdf_values(pdf_factory([conviction_charge, ineligible_charge]), all_expected_values)

    ##### charge.charge_type.severity_level #####

    def test_has_felony_class_c_severity_level(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Felony  Class C and)": "/On",
            "(5 years have passed since the later of the convictionjudgment or release date and)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity in_2)": "/On",
        }
        conviction_charge.charge_type = Mock()
        conviction_charge.charge_type.severity_level = "Felony Class C"
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )

    def test_has_misdemeanor_class_a_severity_level(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Misdemeanor  Class A and)": "/On",
            "(3 years have passed since the later of the convictionjudgment or release date and)": "/On",
            "(I have not been convicted of any other offense or found guilty except for insanity in_3)": "/On",
        }
        conviction_charge.charge_type = Mock()
        conviction_charge.charge_type.severity_level = "Misdemeanor Class A"
        self.assert_pdf_values(
            pdf_factory([conviction_charge]), {**self.expected_conviction_values, **new_expected_values}
        )


class TestBuildUmatillaPDF(TestBuildOregonPDF):
    county = "Umatilla"
    expected_county_data = {
        # county
        "(FOR THE COUNTY OF)": "(Umatilla)",
        # da_address
        "(the District Attorney at address 2)": "(District Attorney - 216 SE 4th St, Pendleton, OR 97801)",
        "(County)": "(Umatilla)",
    }
    expected_conviction_order_values = {
        "(Case Number)": "(base case number)",
        "(Case Name)": "(Case Name 0)",
        "(Arrest Dates)": "(Feb 3, 2020)",
        "(Charges All)": "(A Bad Thing)",
        "(Conviction Dates)": "(Dec 3, 1999)",
        "(Conviction Charges)": "(A Bad Thing)",
    }
    expected_arrest_order_values = {
        "(Case Number)": "(base case number)",
        "(Case Name)": "(Case Name 0)",
        "(Dismissed Arrest Dates)": "(Feb 3, 2020)",
        "(Dismissed Charges)": "(A Bad Thing)",
        "(Dismissed Dates)": "(Jun 7, 2023)",
    }

    # All of the Oregon PDF should be present as well as conviction or arrest order forms.
    def assert_pdf_values(self, pdf: PDF, new_expected_values):
        all_expected_values = {**self.expected_county_data, **self.expected_base_values, **new_expected_values}
        if pdf.mapper["(has_conviction)"]:
            extra = self.expected_conviction_order_values
        else:
            extra = self.expected_arrest_order_values

        assert_pdf_values(pdf, {**all_expected_values, **extra})

    def test_oregon_base_case(self, case: Mock):
        pass

    def test_has_contempt_of_court_and_case_number_with_comments(self, conviction_charge: Mock, pdf_factory: Callable):
        new_expected_values = {
            "(Case No)": "(base case number)",
            "(contempt of court finding)": "/On",
        }
        conviction_charge.charge_type = ContemptOfCourt()

        all_expected_values = {
            **self.expected_conviction_values,
            **self.expected_violation_values,
            **new_expected_values,
        }
        self.assert_pdf_values(pdf_factory([conviction_charge]), all_expected_values)


class TestBuildMultnomahPDF(PDFTestFixtures):
    county = "Multnomah"

    @pytest.fixture
    def conviction_charge_factory(self) -> Callable:
        def factory(disposition_year=1999, disposition_month=12, disposition_day=3):
            charge = Mock(spec=Charge)
            charge.date = create_date(2020, 2, 3)
            charge.name = "a bad thing"
            charge.edit_status = "not delete"
            charge.expungement_result.charge_eligibility.status = ChargeEligibilityStatus.ELIGIBLE_NOW
            charge.charge_type = FelonyClassB()
            charge.disposition = Mock()
            charge.disposition.date = create_date(disposition_year, disposition_month, disposition_day)
            charge.convicted.return_value = True
            charge.dismissed.return_value = False
            charge.probation_revoked = False
            return charge

        return factory

    def test_conviction(self, pdf_factory: Callable, conviction_charge_factory: Callable):
        expected_values = {
            "(Case Number)": "(base case number)",
            "(DA Number)": "(DA num 0)",
            "(Case Name)": "(Case Name 0)",
            "(Full Name)": "(foo bar)",
            "(Date of Birth)": "(1/2/1999)",
            "(Mailing Address)": "(1234 NE Dev St. #12)",
            "(Phone Number)": "(555-555-1234)",
            "(City)": "(Portland)",
            "(State)": "(OR)",
            "(Zip Code)": "(97111)",
            "(Conviction Dates)": "(Mar 9, 2000; Apr 1, 2001)",
            "(Conviction Charges)": "(A Bad Thing; A Bad Thing)",
            "(Arrest Dates)": "(Feb 3, 2020)",
            "(Full Name---)": "(foo bar)",
        }
        charges = [conviction_charge_factory(2000, 3, 9), conviction_charge_factory(2001, 4, 1)]
        assert_pdf_values(pdf_factory(charges), expected_values)

    def test_arrest(self, pdf_factory: Callable, dismissed_charge_factory: Callable):
        expected_values = {
            "(Case Number)": "(base case number)",
            "(DA Number)": "(DA num 0)",
            "(Case Name)": "(Case Name 0)",
            "(Full Name)": "(foo bar)",
            "(Date of Birth)": "(1/2/1999)",
            "(Mailing Address)": "(1234 NE Dev St. #12)",
            "(Phone Number)": "(555-555-1234)",
            "(City)": "(Portland)",
            "(State)": "(OR)",
            "(Zip Code)": "(97111)",
            "(Dismissed Arrest Dates)": "(Apr 1, 2001; Mar 9, 2000)",
            "(Dismissed Charges)": "(A Bad Thing; A Bad Thing)",
            "(DA Number)": "(DA num 0)",
            "(Full Name---)": "(foo bar)",
        }
        charges = [dismissed_charge_factory(2001, 4, 1), dismissed_charge_factory(2000, 3, 9)]
        assert_pdf_values(pdf_factory(charges), expected_values)

    @patch("expungeservice.form_filling.PdfWriter")
    def test_font_shrinking_and_pdf_write_text(self, MockPdfWriter, pdf_factory: Mock, dismissed_charge_factory: Mock):
        charge_name = (
            "A.............. Very.................... Long................. Name......................"
            + "A.............. Very.................... Long................. Name......................"
        )
        expected_values = {
            "(Case Number)": "(base case number)",
            "(DA Number)": "(DA num 0)",
            "(Case Name)": "(Case Name 0)",
            "(Full Name)": "(foo bar)",
            "(Date of Birth)": "(1/2/1999)",
            "(Mailing Address)": "(1234 NE Dev St. #12)",
            "(Phone Number)": "(555-555-1234)",
            "(City)": "(Portland)",
            "(State)": "(OR)",
            "(Zip Code)": "(97111)",
            "(Dismissed Arrest Dates)": "(Feb 3, 2020)",
            "(Dismissed Charges)": f"({charge_name})",
            "(Case Number)": "(base case number)",
            "(Full Name)": "(foo bar)",
            "(DA Number)": "(DA num 0)",
            "(Full Name---)": "(foo bar)",
        }
        charge = dismissed_charge_factory()
        charge.name = charge_name
        pdf: PDF = pdf_factory([charge])

        assert pdf.shrunk_fields.get("(Dismissed Charges)") == f"({charge_name})"
        assert len(pdf.shrunk_fields) == 1
        assert pdf.get_annotation_dict()["(Dismissed Charges)"].DA == "(/TimesNewRoman 6 Tf 0 g)"
        assert_pdf_values(pdf, expected_values)

        assert not MockPdfWriter.return_value.addpages.called
        pdf.add_text("foo text")
        assert MockPdfWriter.return_value.addpages.called
