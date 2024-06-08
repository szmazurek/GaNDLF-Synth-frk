import pandas as pd
import os, pickle, shutil
from pathlib import Path
from warnings import warn
from logging import Logger, basicConfig

from torchio.transforms import Compose

from gandlf_synth.models.configs.config_abc import AbstractModelConfig
from gandlf_synth.models.modules.module_factory import ModuleFactory
from gandlf_synth.data.datasets_factory import DatasetFactory
from gandlf_synth.data.dataloaders_factory import DataloaderFactory
from gandlf_synth.metrics import get_metrics
from gandlf_synth.data.preprocessing import get_preprocessing_transforms
from gandlf_synth.data.augmentations import get_augmentation_transforms


from typing import List, Optional, Type, Union

# TODO this config is temporary/scratch
BASIC_LOGGER_CONFIG = basicConfig(
    filemode="w",
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level="INFO",
)


class TrainingManager:
    """
    A class to manage the training process of a model. This class ties all the necessary
    components together to train a model.
    """

    def __init__(
        self,
        train_dataframe: pd.DataFrame,
        output_dir: str,
        global_config: dict,
        model_config: Type[AbstractModelConfig],
        resume: bool,
        reset: bool,
        device: str,
        val_dataframe: Optional[pd.DataFrame] = None,
        test_dataframe: Optional[pd.DataFrame] = None,
        val_ratio: Optional[float] = 0,
        test_ratio: Optional[float] = 0,
    ):
        """
        Initialize the TrainingManager.

        Args:
            train_dataframe (pd.DataFrame): The training dataframe.
            output_dir (str): The main output directory.
            global_config (dict): The global configuration dictionary.
            model_config (Type[AbstractModelConfig]): The model configuration object.
            resume (bool): Whether the previous run will be resumed or not.
            reset (bool): Whether the previous run will be reset or not.
            device (str): The device to perform computations on.
            val_dataframe (pd.DataFrame, optional): The validation dataframe. Defaults to None.
            test_dataframe (pd.DataFrame, optional): The test dataframe. Defaults to None.
            val_ratio (float, optional): The percentage of data to be used for validation,
        extracted from the training dataframe. This parameter will be used if val_dataframe is None.
        If test_ratio is also specified, testing data will be extracted first, and then the
        remaining data will be split into training and validation data. Defaults to 0.
            test_ratio (float, optional): The percentage of data to be used for testing,
        extracted from the training dataframe. This parameter will be used if test_dataframe is None. Defaults to 0.
        """

        self.train_dataframe = train_dataframe
        self.val_dataframe = val_dataframe
        self.test_dataframe = test_dataframe
        self.val_ratio = val_ratio
        self.test_ratio = test_ratio
        self.output_dir = output_dir
        self.global_config = global_config
        self.model_config = model_config
        self.resume = resume
        self.reset = reset
        self.device = device
        self._assert_parameter_correctness()
        self._warn_user()

        self.metric_calculator_dict = self._prepare_metric_calculator()
        self.postprocessing_transforms = self._prepare_postprocessing_transforms()
        self.logger = self._prepare_logger()

        (
            self.train_dataloader,
            self.val_dataloader,
            self.test_dataloader,
        ) = self._prepare_dataloaders()

        module_factory = ModuleFactory(
            model_config=self.model_config,
            logger=self.logger,
            metric_calculator=self.metric_calculator_dict,
            device=self.device,
        )
        self.module = module_factory.get_module()

    def _warn_user(self):
        """
        Warn the user about the validation and testing configuration.
        """
        if self.val_dataframe is None and self.val_ratio == 0:
            warn(
                "Validation data is not provided and the validation ratio is set to 0. "
                "The model will not be validated during the training process.",
                UserWarning,
            )
        if self.test_dataframe is None and self.test_ratio == 0:
            warn(
                "Test data is not provided and the test ratio is set to 0. "
                "The model will not be tested after the training process.",
                UserWarning,
            )
        if self.val_dataframe is not None and self.val_ratio != 0:
            warn(
                "Validation data is provided and the validation ratio is set to a non-zero value. "
                "The validation data provided will be used for validation, and the validation ratio will be ignored.",
                UserWarning,
            )
        if self.test_dataframe is not None and self.test_ratio != 0:
            warn(
                "Test data is provided and the test ratio is set to a non-zero value. "
                "The test data provided will be used for testing, and the test ratio will be ignored.",
                UserWarning,
            )
        if self.val_dataframe is None and self.val_ratio != 0:
            warn(
                "Validation data is not provided, and the validation ratio is set to a non-zero value. "
                "Validation data will be extracted from the training data.",
                "IMPORTANT: samples from the training data will be RANDOMLY selected REGARDLESS of the subjects they come from.",
                "If you want to avoid samples from the same subject to be split between training and validation, provide a validation dataframe.",
                UserWarning,
            )
        if self.test_dataframe is None and self.test_ratio != 0:
            warn(
                "Test data is not provided, and the test ratio is set to a non-zero value. "
                "Test data will be extracted from the training data.",
                "IMPORTANT: samples from the training data will be RANDOMLY selected REGARDLESS of the subjects they come from.",
                "If you want to avoid samples from the same subject to be split between training and testing, provide a test dataframe.",
                UserWarning,
            )

    def _assert_parameter_correctness(self):
        """
        Assert the correctness of the parameters.
        """
        assert (
            self.val_ratio >= 0 and self.val_ratio <= 1
        ), "Validation ratio must be between 0 and 1"
        assert (
            self.test_ratio >= 0 and self.test_ratio <= 1
        ), "Test ratio must be between 0 and 1"
        assert (
            self.val_ratio + self.test_ratio <= 1
        ), "Validation and test ratios must sum up to less than or equal to 1"

    def _prepare_metric_calculator(self) -> dict:
        """
        Prepare the metric calculator for the training process.

        Returns:
            dict: The dictionary of metrics to be calculated.
        """
        return get_metrics(self.global_config["metrics"])

    def _prepare_logger(self) -> Logger:
        """
        Prepare the logger for the training process.
        """
        logger = Logger("GandlfSynthTrainingManager")
        return logger

    # TODO
    def _prepare_postprocessing_transforms(self) -> Compose:
        """
        Prepare the postprocessing transforms
        """
        print("Preparing postprocessing transforms")
        pass

    @staticmethod
    def _prepare_transforms(
        preprocessing_config: dict,
        augmentations_config: dict,
        mode: str,
        input_shape: tuple,
    ) -> Compose:
        """
        Prepare the transforms for the training, validation, and testing datasets.

        Args:
            preprocessing_config (dict): The preprocessing configuration.
            augmentations_config (dict): The augmentations configuration.
            mode (str): The mode for which the transforms are being prepared (train, val, test).
            input_shape (tuple): The input shape of the data.
        """
        assert mode in [
            "train",
            "val",
            "test",
        ], "Mode must be one of 'train', 'val', or 'test'"
        transforms_list = []
        preprocessing_operations = preprocessing_config.get(mode)
        augmentation_operations = augmentations_config.get(mode)
        if preprocessing_operations is not None:
            train_mode = True if mode == "train" else False
            preprocessing_transforms = get_preprocessing_transforms(
                preprocessing_operations, train_mode, input_shape
            )
            transforms_list.extend(preprocessing_transforms)
        # as in Gandlf, we will use augmentations only in training mode
        if augmentation_operations is not None and mode == "train":
            augmentation_transforms = get_augmentation_transforms(
                augmentation_operations
            )
            transforms_list.extend(augmentation_transforms)
        if len(transforms_list) > 0:
            return Compose(transforms_list)

    @staticmethod
    def _extract_random_data_from_dataframe(dataframe: pd.DataFrame, ratio: float):
        """
        Extracts random data indices from the dataframe based on the ratio.
        Chosen indices are removed from the original dataframe in place.
        Args:
            dataframe (pd.DataFrame): The dataframe to extract data from.
            ratio (float): The ratio of data to be extracted.

        Returns:
            pd.DataFrame: The extracted data.
        """
        num_samples_to_extract = int(len(dataframe) * ratio)
        random_rows = dataframe.sample(num_samples_to_extract, replace=False)
        dataframe.drop(random_rows.index, inplace=True)
        new_dataframe = pd.DataFrame(random_rows, columns=dataframe.columns)

        return new_dataframe

    def _prepare_dataloaders(self) -> tuple:
        """
        Prepare the dataloaders for the training, validation, and testing datasets.
        """
        dataset_factory = DatasetFactory()
        dataloader_factory = DataloaderFactory(params=self.global_config)
        preprocessing_config = self.global_config.get("data_preprocessing")
        augmentations_config = self.global_config.get("data_augmentations")

        # Extract validation and test data if not provided and ratios are specified
        if self.test_dataframe is None and self.test_ratio != 0:
            self.test_dataframe = self._extract_random_data_from_dataframe(
                self.train_dataframe, self.test_ratio
            )
        if self.val_dataframe is None and self.val_ratio != 0:
            self.val_dataframe = self._extract_random_data_from_dataframe(
                self.train_dataframe, self.val_ratio
            )
        train_transforms = self._prepare_transforms(
            preprocessing_config,
            augmentations_config,
            "train",
            self.model_config.architecture["input_shape"],
        )
        train_dataset = dataset_factory.get_dataset(
            self.train_dataframe, train_transforms, self.model_config.labeling_paradigm
        )
        train_dataloader = dataloader_factory.get_training_dataloader(train_dataset)
        # Here we need to consider cases where user did not specify val or test dataframes
        val_dataloader = None
        test_dataloader = None
        if self.val_dataframe is not None:
            val_transforms = self._prepare_transforms(
                preprocessing_config,
                augmentations_config,
                "val",
                self.model_config.architecture["input_shape"],
            )
            val_dataset = dataset_factory.get_dataset(
                self.val_dataframe, val_transforms, self.model_config.labeling_paradigm
            )
            val_dataloader = dataloader_factory.get_validation_dataloader(val_dataset)
        if self.test_dataframe is not None:
            test_transforms = self._prepare_transforms(
                preprocessing_config,
                augmentations_config,
                "test",
                self.model_config.architecture["input_shape"],
            )
            test_dataset = dataset_factory.get_dataset(
                self.test_dataframe,
                test_transforms,
                self.model_config.labeling_paradigm,
            )
            test_dataloader = dataloader_factory.get_testing_dataloader(test_dataset)

        return train_dataloader, val_dataloader, test_dataloader

    # TODO: this is still WIP, here we need to handle things like model saving
    # etc, nevertheless, the basic idea is there
    # Also I did not yet figure out the resume part, DCGAN Module needs to
    # implement this method and we need to thking how and where to execute it
    def run_training(self):
        """
        Train the model.
        """
        for epoch in range(self.global_config["num_epochs"]):
            for batch_idx, batch in enumerate(self.train_dataloader):
                train_step_loss = self.module.training_step(batch, batch_idx)
            if self.val_dataloader is not None:
                for batch_idx, batch in enumerate(self.val_dataloader):
                    val_step_loss = self.module.validation_step(batch, batch_idx)
            if self.test_dataloader is not None:
                for batch_idx, batch in enumerate(self.test_dataloader):
                    test_step_loss = self.module.testing_step(batch, batch_idx)