        except Exception as e:
            self.publish_fail += 1
            self.last_error = str(e)
            self.connected = False
            await self.disconnect()
            LOGGER.error("Publish error in device %s: %s", self.device_id, e)
            return False
